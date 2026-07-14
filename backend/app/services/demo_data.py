from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import Candidate, CandidateSkill, Department, JobRequisition
from app.services.matching import rematch_requisition

DEMO_REQUISITIONS = (
    {
        "req_no": "DEMO-BE-001",
        "title": "後端工程師",
        "employment_type": "full_time",
        "work_city": "台北市",
        "salary_min": 65000,
        "salary_max": 95000,
        "salary_type": "monthly",
        "min_years": Decimal("3.0"),
        "education_req": "大學",
        "jd": "設計與維護人才平台 API、資料庫及系統整合，並參與程式碼審查與自動化測試。",
        "summary": "負責 TalentHub 核心後端服務與資料整合。",
        "skills": ["Python", "FastAPI", "SQL", "PostgreSQL", "Git"],
        "match_weights": {
            "required_skills": ["Python", "SQL"],
            "preferred_skills": ["FastAPI", "PostgreSQL", "Git"],
        },
    },
    {
        "req_no": "DEMO-DA-001",
        "title": "資料分析師",
        "employment_type": "full_time",
        "work_city": "台北市",
        "salary_min": 55000,
        "salary_max": 80000,
        "salary_type": "monthly",
        "min_years": Decimal("2.0"),
        "education_req": "大學",
        "jd": "建立營運儀表板、分析招募數據並將洞察轉化為可執行的決策建議。",
        "summary": "以資料協助招募與營運團隊改善決策品質。",
        "skills": ["Excel", "SQL", "Power BI", "Python", "資料視覺化"],
        "match_weights": {
            "required_skills": ["Excel", "SQL"],
            "preferred_skills": ["Power BI", "Python", "資料視覺化"],
        },
    },
    {
        "req_no": "DEMO-PM-001",
        "title": "產品企劃",
        "employment_type": "full_time",
        "work_city": "台北市",
        "salary_min": 52000,
        "salary_max": 78000,
        "salary_type": "monthly",
        "min_years": Decimal("2.0"),
        "education_req": "大學",
        "jd": "蒐集使用者需求、規劃產品功能與時程，協調設計、工程及營運團隊推動交付。",
        "summary": "規劃人才平台體驗並協調跨部門產品交付。",
        "skills": ["產品企劃", "專案管理", "需求分析", "跨部門溝通", "Excel"],
        "match_weights": {
            "required_skills": ["專案管理", "跨部門溝通"],
            "preferred_skills": ["產品企劃", "需求分析", "Excel"],
        },
    },
    {
        "req_no": "DEMO-FE-001",
        "title": "前端工程師",
        "employment_type": "full_time",
        "work_city": "新北市",
        "salary_min": 60000,
        "salary_max": 90000,
        "salary_type": "monthly",
        "min_years": Decimal("2.0"),
        "education_req": "大學",
        "jd": "開發易用且具互動性的招募介面，維護元件系統並提升網站效能與可及性。",
        "summary": "打造清楚、溫暖且高互動的人才平台介面。",
        "skills": ["Vue", "TypeScript", "HTML", "CSS", "Git"],
        "match_weights": {
            "required_skills": ["Vue", "TypeScript"],
            "preferred_skills": ["HTML", "CSS", "Git"],
        },
    },
)


def _require_non_production_demo_environment() -> None:
    environment = get_settings().app_env.strip().lower()
    if environment in {"production", "staging"}:
        raise RuntimeError(f"Demo data seeding is disabled in {environment}")


def seed_demo_requisitions(db: Session) -> list[JobRequisition]:
    """Insert missing demo jobs by stable req_no; never modify existing rows."""

    _require_non_production_demo_environment()
    existing_req_nos = set(db.scalars(select(JobRequisition.req_no)).all())
    department_id = db.scalar(
        select(Department.id).where(Department.is_active.is_(True)).order_by(Department.id)
    )
    now = datetime.now(UTC)
    created: list[JobRequisition] = []
    for definition in DEMO_REQUISITIONS:
        if definition["req_no"] in existing_req_nos:
            continue
        requisition = JobRequisition(
            **definition,
            department_id=department_id,
            headcount=1,
            urgency="normal",
            status="sourcing",
            published_at=now,
        )
        db.add(requisition)
        created.append(requisition)
    db.commit()
    return created


MATCHING_SHOWCASE_JOB = {
    "req_no": "DEMO-MATCH-LEVELS",
    "title": "媒合分數展示職缺",
    "employment_type": "full_time",
    "work_city": "台北市",
    "jd": "用於展示可解釋媒合分數與 HR 條件篩選；此職缺與三位人才皆為展示資料。",
    "summary": "固定展示 100%、75%、50% 三種媒合效果。",
    "skills": ["核心能力", "溝通協作", "資料分析"],
    "match_weights": {
        "skill": 1.0,
        "relevance": 0.0,
        "years": 0.0,
        "salary": 0.0,
        "education": 0.0,
        "location": 0.0,
        "required_skills": ["核心能力"],
        "preferred_skills": ["溝通協作", "資料分析"],
        "require_skills": True,
        "require_years": False,
        "require_education": False,
        "require_location": False,
    },
}

MATCHING_SHOWCASE_CANDIDATES = (
    ("T-DEMO-100", "展示人才－完整符合", ["核心能力", "溝通協作", "資料分析"]),
    ("T-DEMO-075", "展示人才－高度符合", ["核心能力", "溝通協作"]),
    ("T-DEMO-050", "展示人才－部分符合", ["溝通協作", "資料分析"]),
)


def seed_matching_showcase(db: Session) -> tuple[JobRequisition, list[Candidate]]:
    """Upsert isolated showcase data and calculate exact 100/75/50 results."""

    _require_non_production_demo_environment()
    job = db.scalar(
        select(JobRequisition).where(
            JobRequisition.req_no == MATCHING_SHOWCASE_JOB["req_no"]
        )
    )
    if job is None:
        department_id = db.scalar(
            select(Department.id).where(Department.is_active.is_(True)).order_by(Department.id)
        )
        job = JobRequisition(
            **MATCHING_SHOWCASE_JOB,
            department_id=department_id,
            headcount=1,
            urgency="normal",
            status="sourcing",
            published_at=datetime.now(UTC),
        )
        db.add(job)
        db.flush()
    else:
        # These records are explicitly owned by the showcase seed, so rerunning it
        # restores a predictable demo after someone experiments with the filters.
        for key, value in MATCHING_SHOWCASE_JOB.items():
            if key != "req_no":
                setattr(job, key, value)

    candidates: list[Candidate] = []
    for code, name, skills in MATCHING_SHOWCASE_CANDIDATES:
        candidate = db.scalar(select(Candidate).where(Candidate.code == code))
        if candidate is None:
            candidate = Candidate(
                code=code,
                name=name,
                current_title="媒合展示人才",
                total_years=Decimal("3.0"),
                highest_education="大學",
                expected_cities=["台北市"],
                status="new",
                source="demo",
            )
            db.add(candidate)
            db.flush()
        else:
            candidate.name = name
            candidate.deleted_at = None
            candidate.status = "new"
        existing_skills = list(
            db.scalars(select(CandidateSkill).where(CandidateSkill.candidate_id == candidate.id))
        )
        for item in existing_skills:
            db.delete(item)
        db.flush()
        db.add_all(
            CandidateSkill(candidate_id=candidate.id, skill=skill, skill_norm=skill.casefold())
            for skill in skills
        )
        candidates.append(candidate)

    db.commit()
    db.refresh(job)
    rematch_requisition(db, job)
    return job, candidates
