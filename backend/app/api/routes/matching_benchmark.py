from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.dependencies.auth import get_current_user
from app.models.organization import User
from app.schemas.matching_benchmark import (
    BenchmarkRatingRead,
    BenchmarkRatingWrite,
    BenchmarkReport,
    BenchmarkSuiteRead,
    BlindBenchmarkCaseList,
)
from app.services.matching_benchmark import (
    BenchmarkAccessError,
    BenchmarkConflictError,
    BenchmarkError,
    BenchmarkNotFoundError,
    BenchmarkStateError,
    blind_cases_payload,
    build_benchmark_report,
    get_benchmark_suite,
    list_suite_payloads,
    reveal_benchmark_suite,
    save_blind_rating,
    suite_payload,
)

router = APIRouter(prefix="/matching-benchmark")


def _raise_http(error: BenchmarkError) -> None:
    if isinstance(error, BenchmarkNotFoundError):
        code = status.HTTP_404_NOT_FOUND
    elif isinstance(error, BenchmarkAccessError):
        code = status.HTTP_403_FORBIDDEN
    elif isinstance(error, BenchmarkConflictError):
        code = status.HTTP_409_CONFLICT
    elif isinstance(error, BenchmarkStateError):
        code = status.HTTP_409_CONFLICT
    else:
        code = status.HTTP_400_BAD_REQUEST
    raise HTTPException(status_code=code, detail=str(error)) from error


def _require_viewer(user: User) -> None:
    if user.role not in {"hr", "manager"}:
        raise HTTPException(status_code=403, detail="Recruiting access required")


@router.get("/suites", response_model=list[BenchmarkSuiteRead])
def list_suites(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[dict]:
    _require_viewer(user)
    return list_suite_payloads(db)


@router.get("/suites/{suite_key}/cases", response_model=BlindBenchmarkCaseList)
def list_blind_cases(
    suite_key: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    try:
        suite = get_benchmark_suite(db, suite_key)
        return blind_cases_payload(db, suite, user)
    except BenchmarkError as error:
        _raise_http(error)


@router.put(
    "/suites/{suite_key}/cases/{case_key}/my-rating",
    response_model=BenchmarkRatingRead,
)
def put_blind_rating(
    suite_key: str,
    case_key: str,
    payload: BenchmarkRatingWrite,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> BenchmarkRatingRead:
    try:
        suite = get_benchmark_suite(db, suite_key)
        rating = save_blind_rating(db, suite, case_key, user, payload)
        return BenchmarkRatingRead.model_validate(rating)
    except BenchmarkError as error:
        _raise_http(error)


@router.post("/suites/{suite_key}/reveal", response_model=BenchmarkSuiteRead)
def reveal_suite(
    suite_key: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    try:
        suite = get_benchmark_suite(db, suite_key)
        reveal_benchmark_suite(db, suite, user)
        return suite_payload(db, suite)
    except BenchmarkError as error:
        _raise_http(error)


@router.get("/suites/{suite_key}/report", response_model=BenchmarkReport)
def get_report(
    suite_key: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    _require_viewer(user)
    try:
        suite = get_benchmark_suite(db, suite_key)
        return build_benchmark_report(db, suite)
    except BenchmarkError as error:
        _raise_http(error)
