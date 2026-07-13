from app import models  # noqa: F401
from app.db.base import Base


def test_core_tables_are_registered() -> None:
    expected = {
        "departments",
        "users",
        "candidates",
        "candidate_educations",
        "candidate_experiences",
    }

    assert expected <= set(Base.metadata.tables)
