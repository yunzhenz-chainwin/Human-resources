from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import (
    Candidate,
    CandidateActivity,
    CandidateEducation,
    CandidateExperience,
    CandidateSkill,
    Department,
    JobApplication,
    JobRequisition,
    SkillCatalog,
    SystemSetting,
    Tag,
    User,
)
from app.services.matching import rematch_requisition
from app.services.security import hash_password

DEPARTMENT_NAMES = (
    "資訊技術部",
    "人力資源部",
    "產品設計部",
    "資料分析部",
    "業務發展部",
)

# Local demonstration accounts. This seed is blocked in staging/production.
DEPARTMENT_ACCOUNT_DEFINITIONS = (
    ("it_manager", "dept.it@example.test", "資訊技術部主管", "資訊技術部"),
    ("hr_manager", "dept.hr@example.test", "人力資源部主管", "人力資源部"),
    ("design", "dept.design@example.test", "產品設計部主管", "產品設計部"),
    ("data", "dept.data@example.test", "資料分析部主管", "資料分析部"),
    ("sales", "dept.sales@example.test", "業務發展部主管", "業務發展部"),
)

SKILL_NAMES = (
    "Python",
    "FastAPI",
    "PostgreSQL",
    "SQL",
    "Vue",
    "TypeScript",
    "HTML",
    "CSS",
    "Excel",
    "Power BI",
    "資料視覺化",
    "人才搜尋",
    "招募面談",
    "Figma",
    "使用者研究",
    "B2B 業務",
    "CRM",
    "跨部門溝通",
)

TAG_DEFINITIONS = (
    ("優先聯繫", "candidate"),
    ("主動應徵", "candidate"),
    ("人才庫推薦", "candidate"),
    ("技術職", "job"),
    ("營運職", "job"),
)

SETTING_DEFINITIONS = (
    ("matching.default_min_score", 60, "媒合頁預設最低分數"),
    ("candidate.retention_years", 2, "人才同意後的預設資料保存年限"),
    (
        "resume.allowed_extensions",
        ["pdf", "doc", "docx"],
        "履歷上傳允許的副檔名",
    ),
)

JOB_DEFINITIONS = (
    {
        "req_no": "R2026-IT-001",
        "title": "資深後端工程師",
        "department": "資訊技術部",
        "employment_type": "full_time",
        "work_city": "台北市",
        "salary_min": 70000,
        "salary_max": 110000,
        "min_years": Decimal("4.0"),
        "education_req": "大學",
        "summary": "負責人才平台 API、資料庫與系統整合。",
        "jd": "設計與維護 FastAPI 服務、PostgreSQL 資料模型、自動化測試及服務監控。",
        "skills": ["Python", "FastAPI", "PostgreSQL", "SQL"],
    },
    {
        "req_no": "R2026-IT-002",
        "title": "前端工程師",
        "department": "資訊技術部",
        "employment_type": "full_time",
        "work_city": "新北市",
        "salary_min": 60000,
        "salary_max": 95000,
        "min_years": Decimal("2.0"),
        "education_req": "大學",
        "summary": "打造清楚、溫暖且具互動性的人才平台介面。",
        "jd": "使用 Vue 與 TypeScript 開發前端功能，維護元件、效能與無障礙體驗。",
        "skills": ["Vue", "TypeScript", "HTML", "CSS"],
    },
    {
        "req_no": "R2026-DA-001",
        "title": "數據分析師",
        "department": "資料分析部",
        "employment_type": "full_time",
        "work_city": "台北市",
        "salary_min": 55000,
        "salary_max": 85000,
        "min_years": Decimal("2.0"),
        "education_req": "大學",
        "summary": "分析招募與營運資料並建立決策儀表板。",
        "jd": "使用 SQL、Excel 與 Power BI 建立指標、資料模型及視覺化報表。",
        "skills": ["SQL", "Excel", "Power BI", "資料視覺化"],
    },
    {
        "req_no": "R2026-HR-001",
        "title": "人才招募專員",
        "department": "人力資源部",
        "employment_type": "full_time",
        "work_city": "台北市",
        "salary_min": 45000,
        "salary_max": 65000,
        "min_years": Decimal("2.0"),
        "education_req": "大學",
        "summary": "負責人才搜尋、面談安排與招募流程改善。",
        "jd": "管理職缺、主動搜尋人才、執行面談並追蹤招募成效與候選人體驗。",
        "skills": ["人才搜尋", "招募面談", "Excel", "跨部門溝通"],
    },
    {
        "req_no": "R2026-UX-001",
        "title": "UI／UX 設計師",
        "department": "產品設計部",
        "employment_type": "full_time",
        "work_city": "台北市",
        "salary_min": 55000,
        "salary_max": 85000,
        "min_years": Decimal("2.0"),
        "education_req": "專科",
        "summary": "規劃人才與招募人員的端到端產品體驗。",
        "jd": "執行使用者研究、流程設計、原型製作與設計系統維護。",
        "skills": ["Figma", "使用者研究", "跨部門溝通"],
    },
    {
        "req_no": "R2026-BD-001",
        "title": "企業客戶經理",
        "department": "業務發展部",
        "employment_type": "full_time",
        "work_city": "台北市",
        "salary_min": 50000,
        "salary_max": 90000,
        "min_years": Decimal("3.0"),
        "education_req": "專科",
        "summary": "開發企業客戶並推動人才平台合作方案。",
        "jd": "管理銷售管線、需求訪談、方案簡報、合約協調與客戶關係。",
        "skills": ["B2B 業務", "CRM", "跨部門溝通"],
    },
)

SAMPLE_CANDIDATES = (
    {
        "code": "SAMPLE-2026-001",
        "name": "展示人才－林怡君",
        "email": "sample.backend@example.test",
        "phone": "0900-000-001",
        "city": "台北市",
        "current_title": "後端工程師",
        "total_years": Decimal("5.0"),
        "highest_education": "大學",
        "expected_title": "資深後端工程師",
        "expected_cities": ["台北市"],
        "skills": ["Python", "FastAPI", "PostgreSQL", "SQL"],
        "job_req_no": "R2026-IT-001",
    },
    {
        "code": "SAMPLE-2026-002",
        "name": "展示人才－王建文",
        "email": "sample.frontend@example.test",
        "phone": "0900-000-002",
        "city": "新北市",
        "current_title": "前端工程師",
        "total_years": Decimal("3.0"),
        "highest_education": "大學",
        "expected_title": "前端工程師",
        "expected_cities": ["新北市", "台北市"],
        "skills": ["Vue", "TypeScript", "HTML", "CSS"],
        "job_req_no": "R2026-IT-002",
    },
    {
        "code": "SAMPLE-2026-003",
        "name": "展示人才－陳思妤",
        "email": "sample.data@example.test",
        "phone": "0900-000-003",
        "city": "台北市",
        "current_title": "資料分析師",
        "total_years": Decimal("4.0"),
        "highest_education": "碩士",
        "expected_title": "數據分析師",
        "expected_cities": ["台北市"],
        "skills": ["SQL", "Excel", "Power BI", "資料視覺化"],
        "job_req_no": "R2026-DA-001",
    },
    {
        "code": "SAMPLE-2026-004",
        "name": "展示人才－張雅婷",
        "email": "sample.hr@example.test",
        "phone": "0900-000-004",
        "city": "台北市",
        "current_title": "招募顧問",
        "total_years": Decimal("3.0"),
        "highest_education": "大學",
        "expected_title": "人才招募專員",
        "expected_cities": ["台北市"],
        "skills": ["人才搜尋", "招募面談", "Excel", "跨部門溝通"],
        "job_req_no": "R2026-HR-001",
    },
)


def _require_development() -> None:
    environment = get_settings().app_env.strip().lower()
    if environment in {"production", "staging"}:
        raise RuntimeError(f"Initial sample data is disabled in {environment}")


def seed_initial_data(db: Session) -> dict[str, int]:
    """Create useful local records once; reruns only fill missing stable keys."""

    _require_development()
    counts = {
        "departments": 0,
        "department_users": 0,
        "department_users_renamed": 0,
        "skills": 0,
        "tags": 0,
        "settings": 0,
        "jobs": 0,
        "candidates": 0,
        "educations": 0,
        "experiences": 0,
        "candidate_skills": 0,
        "activities": 0,
        "applications": 0,
    }

    departments = {
        item.name: item for item in db.scalars(select(Department)).all()
    }
    for name in DEPARTMENT_NAMES:
        if name not in departments:
            item = Department(name=name, is_active=True)
            db.add(item)
            db.flush()
            departments[name] = item
            counts["departments"] += 1

    existing_users = db.scalars(select(User)).all()
    existing_usernames = {item.username for item in existing_users}
    existing_users_by_email = {item.email: item for item in existing_users}
    for username, email, display_name, department_name in DEPARTMENT_ACCOUNT_DEFINITIONS:
        existing_user = existing_users_by_email.get(email)
        if existing_user is not None:
            if existing_user.username != username and username not in existing_usernames:
                existing_usernames.discard(existing_user.username)
                existing_user.username = username
                existing_usernames.add(username)
                counts["department_users_renamed"] += 1
            continue
        if username in existing_usernames:
            continue
        user = User(
            username=username,
            email=email,
            password_hash=hash_password("dept123"),
            display_name=display_name,
            role="manager",
            department_id=departments[department_name].id,
            is_active=True,
        )
        db.add(user)
        existing_usernames.add(username)
        existing_users_by_email[email] = user
        counts["department_users"] += 1

    existing_skills = {
        item.name_norm for item in db.scalars(select(SkillCatalog)).all()
    }
    for name in SKILL_NAMES:
        normalized = name.casefold()
        if normalized not in existing_skills:
            db.add(SkillCatalog(name=name, name_norm=normalized, is_active=True))
            existing_skills.add(normalized)
            counts["skills"] += 1

    existing_tags = {
        (item.name, item.category) for item in db.scalars(select(Tag)).all()
    }
    for name, category in TAG_DEFINITIONS:
        if (name, category) not in existing_tags:
            db.add(Tag(name=name, category=category, is_active=True))
            existing_tags.add((name, category))
            counts["tags"] += 1

    existing_settings = {
        item.key for item in db.scalars(select(SystemSetting)).all()
    }
    for key, value, description in SETTING_DEFINITIONS:
        if key not in existing_settings:
            db.add(
                SystemSetting(
                    key=key,
                    value=value,
                    description=description,
                    is_secret=False,
                )
            )
            existing_settings.add(key)
            counts["settings"] += 1

    now = datetime.now(UTC)
    jobs = {
        item.req_no: item for item in db.scalars(select(JobRequisition)).all()
    }
    for definition in JOB_DEFINITIONS:
        if definition["req_no"] in jobs:
            continue
        values = {key: value for key, value in definition.items() if key != "department"}
        skills = list(values["skills"])
        job = JobRequisition(
            **values,
            department_id=departments[definition["department"]].id,
            headcount=2 if definition["req_no"] in {"R2026-IT-001", "R2026-HR-001"} else 1,
            salary_type="monthly",
            urgency="normal",
            status="sourcing",
            published_at=now,
            needed_by=date(2026, 9, 30),
            match_weights={
                "required_skills": skills[:2],
                "preferred_skills": skills[2:],
            },
        )
        db.add(job)
        db.flush()
        jobs[job.req_no] = job
        counts["jobs"] += 1

    for definition in SAMPLE_CANDIDATES:
        candidate = db.scalar(
            select(Candidate).where(Candidate.code == definition["code"])
        )
        if candidate is None:
            candidate = Candidate(
                code=definition["code"],
                name=definition["name"],
                email=definition["email"],
                email_norm=definition["email"].casefold(),
                phone=definition["phone"],
                phone_norm=definition["phone"].replace("-", ""),
                city=definition["city"],
                current_title=definition["current_title"],
                total_years=definition["total_years"],
                highest_education=definition["highest_education"],
                expected_title=definition["expected_title"],
                expected_cities=definition["expected_cities"],
                source="sample",
                source_note="系統初始化展示資料",
                status="new",
                consent_status="internal_sample",
            )
            db.add(candidate)
            db.flush()
            counts["candidates"] += 1

        education = db.scalar(
            select(CandidateEducation).where(
                CandidateEducation.candidate_id == candidate.id,
                CandidateEducation.sort_order == 0,
            )
        )
        if education is None:
            db.add(
                CandidateEducation(
                    candidate_id=candidate.id,
                    school="範例科技大學",
                    major="資訊與管理相關科系",
                    degree=definition["highest_education"],
                    start_ym="2015-09",
                    end_ym="2019-06",
                    is_graduated=True,
                    sort_order=0,
                )
            )
            counts["educations"] += 1

        experience = db.scalar(
            select(CandidateExperience).where(
                CandidateExperience.candidate_id == candidate.id,
                CandidateExperience.sort_order == 0,
            )
        )
        if experience is None:
            db.add(
                CandidateExperience(
                    candidate_id=candidate.id,
                    company="範例數位股份有限公司",
                    title=definition["current_title"],
                    industry="軟體及企業服務",
                    start_ym="2021-01",
                    end_ym=None,
                    years=definition["total_years"],
                    description="負責跨部門專案執行與成果交付。",
                    sort_order=0,
                )
            )
            counts["experiences"] += 1

        existing_candidate_skills = set(
            db.scalars(
                select(CandidateSkill.skill_norm).where(
                    CandidateSkill.candidate_id == candidate.id
                )
            )
        )
        for skill in definition["skills"]:
            normalized = skill.casefold()
            if normalized not in existing_candidate_skills:
                db.add(
                    CandidateSkill(
                        candidate_id=candidate.id,
                        skill=skill,
                        skill_norm=normalized,
                    )
                )
                existing_candidate_skills.add(normalized)
                counts["candidate_skills"] += 1

        activity = db.scalar(
            select(CandidateActivity).where(
                CandidateActivity.candidate_id == candidate.id,
                CandidateActivity.content == "系統已建立展示人才資料，可由 HR 繼續維護。",
            )
        )
        if activity is None:
            db.add(
                CandidateActivity(
                    candidate_id=candidate.id,
                    type="note",
                    content="系統已建立展示人才資料，可由 HR 繼續維護。",
                    happened_at=now,
                )
            )
            counts["activities"] += 1

        job = jobs[definition["job_req_no"]]
        application = db.scalar(
            select(JobApplication).where(
                JobApplication.requisition_id == job.id,
                JobApplication.candidate_id == candidate.id,
            )
        )
        if application is None:
            db.add(
                JobApplication(
                    requisition_id=job.id,
                    candidate_id=candidate.id,
                    status="submitted",
                    source="sample",
                    cover_letter="展示用應徵紀錄，可用來驗證人才與職缺媒合流程。",
                )
            )
            counts["applications"] += 1

    db.commit()
    for job in jobs.values():
        if job.req_no.startswith("R2026-"):
            rematch_requisition(db, job)
    return counts
