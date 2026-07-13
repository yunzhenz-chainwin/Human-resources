from pydantic import BaseModel, Field


class FunnelStage(BaseModel):
    stage: str
    count: int
    conversion_rate: float = Field(ge=0, le=1)


class FunnelReport(BaseModel):
    total: int
    stages: list[FunnelStage]


class TimeToFillItem(BaseModel):
    requisition_id: int
    req_no: str
    title: str
    department_id: int | None
    days: float


class TimeToFillReport(BaseModel):
    filled_count: int
    average_days: float
    items: list[TimeToFillItem]


class SourcePerformance(BaseModel):
    source: str
    total: int
    hired: int
    hire_rate: float = Field(ge=0, le=1)


class SourcesReport(BaseModel):
    total: int
    items: list[SourcePerformance]


class DistributionBucket(BaseModel):
    label: str
    count: int


class MonthlyGrowth(BaseModel):
    month: str
    count: int


class TalentPoolReport(BaseModel):
    total: int
    skills: list[DistributionBucket]
    experience: list[DistributionBucket]
    cities: list[DistributionBucket]
    education: list[DistributionBucket]
    monthly_growth: list[MonthlyGrowth]
