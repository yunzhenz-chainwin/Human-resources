from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy import Integer, case, cast, exists, func, or_, select
from sqlalchemy.orm import Session

from app.models import Candidate, CandidateSkill, JobApplication, JobRequisition

FUNNEL_STAGES = {
    "recommended": {
        "submitted",
        "recommended",
        "shortlisted",
        "contacted",
        # Marked ready to interview but no interview has happened yet, so it counts
        # at the top of the funnel only.
        "interview_ready",
        "interview",
        "interviewing",
        "offered",
        "hired",
    },
    "contacted": {"contacted", "interview", "interviewing", "offered", "hired"},
    "interview": {"interview", "interviewing", "offered", "hired"},
    "hired": {"hired"},
}


def _formal_candidate_filters():
    return (
        or_(Candidate.source.is_(None), func.lower(Candidate.source) != "demo"),
        ~Candidate.code.startswith("T-DEMO-"),
    )


def _formal_requisition_filter():
    return ~JobRequisition.req_no.startswith("DEMO-")


def date_bounds(
    from_date: date | None, to_date: date | None
) -> tuple[datetime | None, datetime | None]:
    start = datetime.combine(from_date, time.min, tzinfo=UTC) if from_date else None
    end = datetime.combine(to_date + timedelta(days=1), time.min, tzinfo=UTC) if to_date else None
    return start, end


def funnel_report(
    db: Session,
    from_date: date | None = None,
    to_date: date | None = None,
    department_id: int | None = None,
) -> dict:
    start, end = date_bounds(from_date, to_date)
    expressions = [
        func.count(case((JobApplication.status.in_(statuses), 1))).label(stage)
        for stage, statuses in FUNNEL_STAGES.items()
    ]
    query = (
        select(func.count(JobApplication.id).label("total"), *expressions)
        .join(Candidate, Candidate.id == JobApplication.candidate_id)
        .join(JobRequisition, JobRequisition.id == JobApplication.requisition_id)
        .where(
            Candidate.deleted_at.is_(None),
            *_formal_candidate_filters(),
            _formal_requisition_filter(),
        )
    )
    query = _date_filter(query, JobApplication.created_at, start, end)
    if department_id is not None:
        query = query.where(JobRequisition.department_id == department_id)
    row = db.execute(query).one()
    total = int(row.total or 0)
    stages = []
    previous = total
    for name in FUNNEL_STAGES:
        count = int(getattr(row, name) or 0)
        rate = round(count / previous, 4) if previous else 0.0
        stages.append({"stage": name, "count": count, "conversion_rate": rate})
        previous = count
    return {"total": total, "stages": stages}


def time_to_fill_report(
    db: Session,
    from_date: date | None = None,
    to_date: date | None = None,
    department_id: int | None = None,
) -> dict:
    start, end = date_bounds(from_date, to_date)
    query = select(JobRequisition).where(
        JobRequisition.filled_at.is_not(None), _formal_requisition_filter()
    )
    query = _date_filter(query, JobRequisition.filled_at, start, end)
    if department_id is not None:
        query = query.where(JobRequisition.department_id == department_id)
    requisitions = list(db.scalars(query.order_by(JobRequisition.filled_at.desc())).all())
    items = []
    for requisition in requisitions:
        opened_at = requisition.published_at or requisition.created_at
        elapsed = max(0.0, (requisition.filled_at - opened_at).total_seconds() / 86_400)
        items.append(
            {
                "requisition_id": requisition.id,
                "req_no": requisition.req_no,
                "title": requisition.title,
                "department_id": requisition.department_id,
                "days": round(elapsed, 2),
            }
        )
    average = round(sum(item["days"] for item in items) / len(items), 2) if items else 0.0
    return {"filled_count": len(items), "average_days": average, "items": items}


def sources_report(
    db: Session,
    from_date: date | None = None,
    to_date: date | None = None,
    department_id: int | None = None,
) -> dict:
    start, end = date_bounds(from_date, to_date)
    source = func.coalesce(Candidate.source, JobApplication.source, "unknown")
    query = (
        select(
            source.label("source"),
            func.count(JobApplication.id).label("total"),
            func.count(case((JobApplication.status == "hired", 1))).label("hired"),
        )
        .join(Candidate, Candidate.id == JobApplication.candidate_id)
        .join(JobRequisition, JobRequisition.id == JobApplication.requisition_id)
        .where(
            Candidate.deleted_at.is_(None),
            *_formal_candidate_filters(),
            _formal_requisition_filter(),
        )
    )
    query = _date_filter(query, JobApplication.created_at, start, end)
    if department_id is not None:
        query = query.where(JobRequisition.department_id == department_id)
    rows = db.execute(query.group_by(source).order_by(func.count(JobApplication.id).desc(), source))
    items = []
    for row in rows:
        total = int(row.total)
        hired = int(row.hired)
        items.append(
            {
                "source": row.source,
                "total": total,
                "hired": hired,
                "hire_rate": round(hired / total, 4) if total else 0.0,
            }
        )
    return {"total": sum(item["total"] for item in items), "items": items}


def talent_pool_report(
    db: Session,
    from_date: date | None = None,
    to_date: date | None = None,
    department_id: int | None = None,
    skill_limit: int = 20,
) -> dict:
    start, end = date_bounds(from_date, to_date)
    filters = [Candidate.deleted_at.is_(None), *_formal_candidate_filters()]
    if start is not None:
        filters.append(Candidate.created_at >= start)
    if end is not None:
        filters.append(Candidate.created_at < end)
    if department_id is not None:
        filters.append(
            exists(
                select(JobApplication.id)
                .join(JobRequisition, JobRequisition.id == JobApplication.requisition_id)
                .where(
                    JobApplication.candidate_id == Candidate.id,
                    JobRequisition.department_id == department_id,
                )
            )
        )

    total = int(db.scalar(select(func.count(Candidate.id)).where(*filters)) or 0)
    skills = _distribution(
        db,
        select(
            CandidateSkill.skill.label("label"),
            func.count(CandidateSkill.candidate_id).label("count"),
        )
        .join(Candidate, Candidate.id == CandidateSkill.candidate_id)
        .where(*filters)
        .group_by(CandidateSkill.skill)
        .order_by(func.count(CandidateSkill.candidate_id).desc(), CandidateSkill.skill)
        .limit(skill_limit),
    )
    cities = _candidate_distribution(db, Candidate.city, filters, "Unknown")
    education = _candidate_distribution(db, Candidate.highest_education, filters, "Unknown")
    experience_label = case(
        (Candidate.total_years.is_(None), "Unknown"),
        (Candidate.total_years < 1, "<1"),
        (Candidate.total_years < 3, "1-2"),
        (Candidate.total_years < 6, "3-5"),
        (Candidate.total_years < 10, "6-9"),
        else_="10+",
    )
    experience = _distribution(
        db,
        select(experience_label.label("label"), func.count(Candidate.id).label("count"))
        .where(*filters)
        .group_by(experience_label)
        .order_by(experience_label),
    )
    year = cast(func.extract("year", Candidate.created_at), Integer)
    month = cast(func.extract("month", Candidate.created_at), Integer)
    growth_rows = db.execute(
        select(year.label("year"), month.label("month"), func.count(Candidate.id).label("count"))
        .where(*filters)
        .group_by(year, month)
        .order_by(year, month)
    )
    growth = [
        {"month": f"{int(row.year):04d}-{int(row.month):02d}", "count": int(row.count)}
        for row in growth_rows
    ]
    return {
        "total": total,
        "skills": skills,
        "experience": experience,
        "cities": cities,
        "education": education,
        "monthly_growth": growth,
    }


def _date_filter(query, column, start: datetime | None, end: datetime | None):
    if start is not None:
        query = query.where(column >= start)
    if end is not None:
        query = query.where(column < end)
    return query


def _distribution(db: Session, query) -> list[dict]:
    return [{"label": str(row.label), "count": int(row.count)} for row in db.execute(query)]


def _candidate_distribution(db: Session, column, filters: list, unknown: str) -> list[dict]:
    label = func.coalesce(column, unknown)
    return _distribution(
        db,
        select(label.label("label"), func.count(Candidate.id).label("count"))
        .where(*filters)
        .group_by(label)
        .order_by(func.count(Candidate.id).desc(), label),
    )
