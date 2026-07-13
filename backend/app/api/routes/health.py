from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()


class HealthResponse(BaseModel):
    status: Literal["ok"]
    service: str


@router.get("/health", response_model=HealthResponse, summary="服務存活檢查")
def health() -> HealthResponse:
    return HealthResponse(status="ok", service="talenthub-api")
