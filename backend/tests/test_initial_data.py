from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models import (
    Candidate,
    CandidateEducation,
    CandidateExperience,
    CandidateSkill,
    Department,
    JobApplication,
    JobRequisition,
    MatchResult,
    SkillCatalog,
    SystemSetting,
    Tag,
    User,
)
from app.services.initial_data import seed_initial_data


def test_initial_data_populates_related_tables_and_is_idempotent() -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        first = seed_initial_data(db)
        second = seed_initial_data(db)

        assert first["jobs"] == 6
        assert first["candidates"] == 4
        assert first["departments"] == 5
        assert first["department_users"] == 5
        assert first["candidate_skills"] >= 16
        assert all(value == 0 for value in second.values())
        assert db.scalar(select(func.count()).select_from(JobRequisition)) == 6
        assert db.scalar(select(func.count()).select_from(Candidate)) == 4
        assert db.scalar(select(func.count()).select_from(Department)) == 5
        assert db.scalar(select(func.count()).select_from(User)) == 5
        assert set(db.scalars(select(User.username)).all()) == {
            "it_manager",
            "hr_manager",
            "design",
            "data",
            "sales",
        }
        assert set(db.scalars(select(User.department_id)).all()) == set(
            db.scalars(select(Department.id)).all()
        )
        assert db.scalar(select(func.count()).select_from(SkillCatalog)) >= 18
        assert db.scalar(select(func.count()).select_from(Tag)) == 5
        assert db.scalar(select(func.count()).select_from(SystemSetting)) == 3
        assert db.scalar(select(func.count()).select_from(CandidateEducation)) == 4
        assert db.scalar(select(func.count()).select_from(CandidateExperience)) == 4
        assert db.scalar(select(func.count()).select_from(CandidateSkill)) >= 16
        assert db.scalar(select(func.count()).select_from(JobApplication)) == 4
        assert db.scalar(select(func.count()).select_from(MatchResult)) == 24

    Base.metadata.drop_all(engine)
