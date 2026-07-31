from fastapi import APIRouter, Depends

from app.api.routes.admin import router as admin_router
from app.api.routes.applications import router as applications_router
from app.api.routes.auth import router as auth_router
from app.api.routes.candidate_analysis import router as candidate_analysis_router
from app.api.routes.candidates import router as candidates_router
from app.api.routes.deidentified_resumes import router as deidentified_resumes_router
from app.api.routes.department import router as department_router
from app.api.routes.health import router as health_router
from app.api.routes.interview_records import router as interview_records_router
from app.api.routes.matches import router as matches_router
from app.api.routes.matching_benchmark import router as matching_benchmark_router
from app.api.routes.public import router as public_router
from app.api.routes.reports import router as reports_router
from app.api.routes.requisitions import router as requisitions_router
from app.api.routes.resumes import router as resumes_router
from app.api.routes.semantic_shadow import router as semantic_shadow_router
from app.api.routes.talent_retention import router as talent_retention_router
from app.dependencies.auth import require_recruiting_user

api_router = APIRouter()
api_router.include_router(health_router, tags=["system"])
api_router.include_router(public_router, tags=["public"])
api_router.include_router(auth_router, tags=["auth"])
api_router.include_router(department_router, tags=["department"])
api_router.include_router(
    candidates_router, tags=["candidates"], dependencies=[Depends(require_recruiting_user)]
)
api_router.include_router(
    requisitions_router, tags=["requisitions"], dependencies=[Depends(require_recruiting_user)]
)
api_router.include_router(
    resumes_router, tags=["resumes"], dependencies=[Depends(require_recruiting_user)]
)
api_router.include_router(
    deidentified_resumes_router,
    tags=["deidentified-resumes"],
    dependencies=[Depends(require_recruiting_user)],
)
api_router.include_router(
    candidate_analysis_router,
    tags=["candidate-analysis"],
    dependencies=[Depends(require_recruiting_user)],
)
api_router.include_router(talent_retention_router, tags=["talent-retention"])
api_router.include_router(
    applications_router,
    tags=["applications"],
    dependencies=[Depends(require_recruiting_user)],
)
api_router.include_router(
    interview_records_router,
    tags=["application-interviews"],
    dependencies=[Depends(require_recruiting_user)],
)
api_router.include_router(
    matches_router, tags=["matches"], dependencies=[Depends(require_recruiting_user)]
)
api_router.include_router(
    matching_benchmark_router,
    tags=["matching-benchmark"],
    dependencies=[Depends(require_recruiting_user)],
)
api_router.include_router(
    semantic_shadow_router,
    tags=["semantic-shadow"],
    dependencies=[Depends(require_recruiting_user)],
)
api_router.include_router(
    reports_router, tags=["reports"], dependencies=[Depends(require_recruiting_user)]
)
api_router.include_router(admin_router, tags=["admin"])
