from __future__ import annotations

from copy import deepcopy
from typing import Any

SUITE_KEY = "talenthub-small-sample-v1"
SUITE_TITLE = "TalentHub 小樣本媒合盲評基準"
FIXTURE_VERSION = "1.0.0"
SCORING_VERSION = "matching.score_candidate/current"

_JOBS: tuple[dict[str, Any], ...] = (
    {
        "job_key": "backend",
        "title": "Backend Engineer",
        "required_skills": ["Python", "PostgreSQL"],
        "preferred_skills": ["FastAPI", "Docker"],
        "synonym_skills": ["Python", "Postgres", "Fast API", "Docker"],
        "transition_title": "Data Engineer",
        "transition_skills": ["Python", "PostgreSQL", "Docker", "SQL"],
        "unrelated_title": "Retail Store Supervisor",
        "unrelated_skills": ["POS", "Inventory", "Customer Service"],
        "min_years": 3.0,
        "work_city": "臺北市",
        "salary_min": 65000,
        "salary_max": 90000,
    },
    {
        "job_key": "frontend",
        "title": "Frontend Engineer",
        "required_skills": ["Vue", "TypeScript"],
        "preferred_skills": ["HTML", "CSS"],
        "synonym_skills": ["Vue.js", "TS", "HTML", "CSS"],
        "transition_title": "UI Engineer",
        "transition_skills": ["Vue", "TypeScript", "HTML", "Figma"],
        "unrelated_title": "Administrative Assistant",
        "unrelated_skills": ["Word", "Scheduling", "Filing"],
        "min_years": 2.0,
        "work_city": "臺北市",
        "salary_min": 55000,
        "salary_max": 80000,
    },
    {
        "job_key": "data",
        "title": "Data Analyst",
        "required_skills": ["SQL", "Power BI"],
        "preferred_skills": ["Excel", "Python"],
        "synonym_skills": ["SQL", "PowerBI", "Excel", "Python"],
        "transition_title": "Business Operations Analyst",
        "transition_skills": ["SQL", "Power BI", "Excel", "Dashboard"],
        "unrelated_title": "Graphic Designer",
        "unrelated_skills": ["Illustrator", "Photoshop", "Brand Design"],
        "min_years": 2.0,
        "work_city": "新北市",
        "salary_min": 50000,
        "salary_max": 75000,
    },
    {
        "job_key": "recruiting",
        "title": "Talent Acquisition Specialist",
        "required_skills": ["Recruiting", "Excel"],
        "preferred_skills": ["Interviewing", "HRIS"],
        "synonym_skills": ["Recruitment", "Excel", "Candidate Interview", "HRIS"],
        "transition_title": "Customer Success Specialist",
        "transition_skills": ["Recruiting", "Excel", "Stakeholder Communication"],
        "unrelated_title": "Warehouse Operator",
        "unrelated_skills": ["Forklift", "Packing", "Inventory"],
        "min_years": 2.0,
        "work_city": "臺北市",
        "salary_min": 45000,
        "salary_max": 65000,
    },
    {
        "job_key": "sales",
        "title": "B2B Account Manager",
        "required_skills": ["B2B Sales", "CRM"],
        "preferred_skills": ["Negotiation", "Presentation"],
        "synonym_skills": [
            "Business-to-Business Sales",
            "CRM",
            "Negotiation",
            "Presentation",
        ],
        "transition_title": "Partnership Manager",
        "transition_skills": ["B2B Sales", "CRM", "Partnership", "Presentation"],
        "unrelated_title": "Laboratory Technician",
        "unrelated_skills": ["Lab Safety", "Sample Preparation", "Calibration"],
        "min_years": 3.0,
        "work_city": "臺中市",
        "salary_min": 50000,
        "salary_max": 85000,
    },
)


def _job_profile(job: dict[str, Any]) -> dict[str, Any]:
    return {
        "job_key": job["job_key"],
        "title": job["title"],
        "employment_type": "full_time",
        "work_city": job["work_city"],
        "salary_min": job["salary_min"],
        "salary_max": job["salary_max"],
        "min_years": job["min_years"],
        "education_req": None,
        "required_skills": list(job["required_skills"]),
        "preferred_skills": list(job["preferred_skills"]),
        "summary": f"合成職缺：{job['title']}，僅供媒合基準測試。",
    }


def _candidate(
    job: dict[str, Any],
    index: int,
    *,
    title: str | None,
    years: float | None,
    skills: list[str],
    cities: list[str] | None,
    salary_min: int | None,
    salary_max: int | None,
    education: str | None = "學士",
    summary: str | None = "合成履歷摘要；不含姓名、聯絡方式或任何真實個資。",
) -> dict[str, Any]:
    return {
        "synthetic_code": f"BENCH-{job['job_key'].upper()}-{index:02d}",
        "current_title": title,
        "total_years": years,
        "skills": list(skills),
        "highest_education": education,
        "expected_cities": deepcopy(cities),
        "expected_salary_min": salary_min,
        "expected_salary_max": salary_max,
        "summary": summary,
    }


def _cases_for_job(job: dict[str, Any]) -> list[dict[str, Any]]:
    required = list(job["required_skills"])
    preferred = list(job["preferred_skills"])
    all_skills = required + preferred
    salary_min = int(job["salary_min"])
    salary_max = int(job["salary_max"])
    city = str(job["work_city"])
    years = float(job["min_years"])
    cases = [
        (
            "strong",
            "interview",
            _candidate(
                job,
                1,
                title=job["title"],
                years=years + 3,
                skills=all_skills,
                cities=[city],
                salary_min=salary_min,
                salary_max=salary_max,
            ),
        ),
        (
            "strong_variant",
            "interview",
            _candidate(
                job,
                2,
                title=job["title"],
                years=years + 1,
                skills=required + preferred[:1],
                cities=[city],
                salary_min=salary_min,
                salary_max=salary_max - 5000,
            ),
        ),
        (
            "boundary",
            "consider",
            _candidate(
                job,
                3,
                title=job["title"],
                years=years,
                skills=required,
                cities=[city],
                salary_min=salary_max - 5000,
                salary_max=salary_max + 5000,
            ),
        ),
        (
            "skill_synonym",
            "interview",
            _candidate(
                job,
                4,
                title=job["title"],
                years=years + 2,
                skills=list(job["synonym_skills"]),
                cities=[city],
                salary_min=salary_min,
                salary_max=salary_max,
            ),
        ),
        (
            "career_transition",
            "consider",
            _candidate(
                job,
                5,
                title=job["transition_title"],
                years=years + 2,
                skills=list(job["transition_skills"]),
                cities=[city],
                salary_min=salary_min,
                salary_max=salary_max,
                summary="合成轉職案例：具可轉移技能，但職稱與目標職務不同。",
            ),
        ),
        (
            "missing_data",
            "insufficient_data",
            _candidate(
                job,
                6,
                title=None,
                years=None,
                skills=required,
                cities=None,
                salary_min=None,
                salary_max=None,
                education=None,
                summary=None,
            ),
        ),
        (
            "salary_mismatch",
            "reject",
            _candidate(
                job,
                7,
                title=job["title"],
                years=years + 2,
                skills=all_skills,
                cities=[city],
                salary_min=salary_max + 30000,
                salary_max=salary_max + 50000,
            ),
        ),
        (
            "location_mismatch",
            "reject",
            _candidate(
                job,
                8,
                title=job["title"],
                years=years + 2,
                skills=all_skills,
                cities=["高雄市" if city != "高雄市" else "臺北市"],
                salary_min=salary_min,
                salary_max=salary_max,
            ),
        ),
        (
            "experience_gap",
            "reject",
            _candidate(
                job,
                9,
                title=job["title"],
                years=max(0.5, years - 1.5),
                skills=all_skills,
                cities=[city],
                salary_min=salary_min,
                salary_max=salary_max,
            ),
        ),
        (
            "weak",
            "reject",
            _candidate(
                job,
                10,
                title=job["unrelated_title"],
                years=years + 1,
                skills=list(job["unrelated_skills"]),
                cities=["高雄市" if city != "高雄市" else "臺北市"],
                salary_min=salary_min,
                salary_max=salary_max,
            ),
        ),
    ]
    job_profile = _job_profile(job)
    return [
        {
            "case_key": f"{job['job_key']}-{index:02d}",
            "job_key": job["job_key"],
            "scenario": scenario,
            "expected_verdict": expected,
            "job_profile": deepcopy(job_profile),
            "candidate_profile": candidate_profile,
        }
        for index, (scenario, expected, candidate_profile) in enumerate(cases, start=1)
    ]


def build_fixture_cases() -> list[dict[str, Any]]:
    """Return exactly 50 deterministic and PII-free job/resume pairs."""

    cases: list[dict[str, Any]] = []
    for job in _JOBS:
        cases.extend(_cases_for_job(job))
    return [dict(item, sequence=index) for index, item in enumerate(cases, start=1)]

