from collections.abc import Generator
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.session import get_db
from app.dependencies.auth import get_current_user
from app.main import app
from app.models import (
    Candidate,
    CandidateSkill,
    Department,
    JobApplication,
    JobRequisition,
)
from app.services.matching import canonical_skill


@pytest.fixture()
def search_client() -> Generator[tuple[TestClient, dict], None, None]:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    testing_session = sessionmaker(bind=engine, expire_on_commit=False)

    with testing_session() as db:
        engineering = Department(name="Engineering")
        sales = Department(name="Sales")
        db.add_all([engineering, sales])
        db.flush()

        alice = Candidate(
            code="CS-001",
            name="Alice Anderson",
            email="alice@example.com",
            current_title="Backend Engineer",
            status="active",
            total_years=Decimal("6.0"),
            expected_cities=["Taipei", "Tainan"],
            source="direct",
        )
        bob = Candidate(
            code="CS-002",
            name="Bob Brown",
            email="bob@example.com",
            current_title="Frontend Developer",
            status="new",
            total_years=Decimal("2.0"),
            expected_cities=["Kaohsiung"],
            source="direct",
        )
        carol = Candidate(
            code="CS-003",
            name="Carol Chen",
            email="carol@example.com",
            current_title="Data Scientist",
            status="active",
            total_years=Decimal("9.0"),
            expected_cities=["Taipei"],
            source="direct",
        )
        db.add_all([alice, bob, carol])
        db.flush()

        db.add_all(
            [
                CandidateSkill(
                    candidate_id=alice.id, skill="FastAPI", skill_norm=canonical_skill("FastAPI")
                ),
                CandidateSkill(
                    candidate_id=alice.id, skill="Python", skill_norm=canonical_skill("Python")
                ),
                CandidateSkill(
                    candidate_id=carol.id, skill="Python", skill_norm=canonical_skill("Python")
                ),
            ]
        )

        eng_job = JobRequisition(
            req_no="CS-ENG-001",
            title="Backend Engineer",
            department_id=engineering.id,
            employment_type="full_time",
            work_city="Taipei",
            jd="Build things",
            status="approved",
        )
        db.add(eng_job)
        db.flush()
        db.add(
            JobApplication(
                requisition_id=eng_job.id,
                candidate_id=alice.id,
                status="submitted",
                source="career_site",
            )
        )
        db.commit()

        ids = {
            "engineering": engineering.id,
            "sales": sales.id,
            "alice": alice.id,
            "bob": bob.id,
            "carol": carol.id,
        }

    def override_db():
        with testing_session() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id=1, role="admin", department_id=None, is_active=True
    )
    with TestClient(app) as client:
        yield client, ids
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)


def _ids(response) -> set[int]:
    assert response.status_code == 200
    return {row["id"] for row in response.json()}


def test_no_params_returns_all_unchanged(search_client) -> None:
    client, ids = search_client
    response = client.get("/api/v1/candidates")
    assert _ids(response) == {ids["alice"], ids["bob"], ids["carol"]}


def test_keyword_matches_name_title_code_email(search_client) -> None:
    client, ids = search_client
    # name (case-insensitive)
    assert _ids(client.get("/api/v1/candidates?q=alice")) == {ids["alice"]}
    # current_title
    assert _ids(client.get("/api/v1/candidates?q=Developer")) == {ids["bob"]}
    # code
    assert _ids(client.get("/api/v1/candidates?q=CS-003")) == {ids["carol"]}
    # email
    assert _ids(client.get("/api/v1/candidates?q=bob@example.com")) == {ids["bob"]}
    # no match
    assert _ids(client.get("/api/v1/candidates?q=zzz-nobody")) == set()


def test_skill_uses_canonical_normalization(search_client) -> None:
    client, ids = search_client
    # "fast api" -> canonical "fastapi" matches seeded "FastAPI"
    assert _ids(client.get("/api/v1/candidates?skill=fast api")) == {ids["alice"]}
    # Python matches two candidates without duplicate rows
    python_response = client.get("/api/v1/candidates?skill=python")
    assert python_response.status_code == 200
    python_rows = python_response.json()
    assert [row["id"] for row in python_rows].count(ids["alice"]) == 1
    assert {row["id"] for row in python_rows} == {ids["alice"], ids["carol"]}


def test_status_exact_match(search_client) -> None:
    client, ids = search_client
    assert _ids(client.get("/api/v1/candidates?status=active")) == {ids["alice"], ids["carol"]}
    assert _ids(client.get("/api/v1/candidates?status=new")) == {ids["bob"]}


def test_min_years_filter(search_client) -> None:
    client, ids = search_client
    assert _ids(client.get("/api/v1/candidates?min_years=6")) == {ids["alice"], ids["carol"]}
    assert _ids(client.get("/api/v1/candidates?min_years=8")) == {ids["carol"]}


def test_city_membership_no_substring_collision(search_client) -> None:
    client, ids = search_client
    assert _ids(client.get("/api/v1/candidates?city=Taipei")) == {ids["alice"], ids["carol"]}
    assert _ids(client.get("/api/v1/candidates?city=Kaohsiung")) == {ids["bob"]}
    # "Tai" must not match "Taipei"/"Tainan" as a substring
    assert _ids(client.get("/api/v1/candidates?city=Tai")) == set()


def test_department_id_filter(search_client) -> None:
    client, ids = search_client
    # Only Alice has an application tied to Engineering.
    assert _ids(
        client.get(f"/api/v1/candidates?department_id={ids['engineering']}")
    ) == {ids["alice"]}
    assert _ids(client.get(f"/api/v1/candidates?department_id={ids['sales']}")) == set()


def test_combined_filters_are_anded(search_client) -> None:
    client, ids = search_client
    # active + python + >=8 years + Taipei -> only Carol
    response = client.get(
        "/api/v1/candidates?status=active&skill=python&min_years=8&city=Taipei"
    )
    assert _ids(response) == {ids["carol"]}
    # Same filters but status=new yields nothing.
    assert _ids(
        client.get("/api/v1/candidates?status=new&skill=python&min_years=8&city=Taipei")
    ) == set()
