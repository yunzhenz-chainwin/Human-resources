from datetime import datetime
from typing import Literal

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)


class CandidateCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    email: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=50)
    city: str | None = Field(default=None, max_length=50)
    current_title: str | None = Field(default=None, max_length=100)
    total_years: float | None = Field(default=None, ge=0, le=80)
    source: str = "manual"

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str | None) -> str | None:
        if value and ("@" not in value or "." not in value.rsplit("@", 1)[-1]):
            raise ValueError("email 格式不正確")
        return value


class CandidateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    code: str
    name: str
    email: str | None
    phone: str | None
    city: str | None
    current_title: str | None
    total_years: float | None
    source: str | None
    status: str
    has_photo: bool
    photo_updated_at: datetime | None
    created_at: datetime
    updated_at: datetime


class CandidateEducationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    school: str
    major: str | None
    degree: str | None
    start_ym: str | None
    end_ym: str | None
    is_graduated: bool | None
    sort_order: int


class CandidateExperienceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    company: str
    title: str
    industry: str | None
    start_ym: str | None
    end_ym: str | None
    years: float | None
    description: str | None
    sort_order: int


class CandidateUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    email: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=50)
    city: str | None = Field(default=None, max_length=50)
    current_title: str | None = Field(default=None, max_length=100)
    total_years: float | None = Field(default=None, ge=0, le=80)
    source: Literal[
        "manual",
        "p104",
        "p1111",
        "generic",
        "direct",
        "career_site",
        "referral",
        "walk_in",
        "other",
    ] | None = None
    status: str | None = Field(default=None, max_length=20)


class CandidateActivityCreate(BaseModel):
    type: str = Field(
        min_length=1, max_length=20, validation_alias=AliasChoices("type", "activity_type")
    )
    content: str = Field(
        min_length=1, max_length=10000, validation_alias=AliasChoices("content", "note")
    )
    happened_at: datetime | None = None
    next_status: str | None = Field(default=None, max_length=20)


class CandidateActivityRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    candidate_id: int
    user_id: int | None
    author_name: str | None
    author_role: str | None
    author_department_id: int | None
    author_department_name: str | None
    type: str
    content: str
    happened_at: datetime
    created_at: datetime


class RequisitionCreate(BaseModel):
    req_no: str = Field(min_length=1, max_length=20)
    title: str = Field(min_length=1, max_length=100)
    department_id: int | None = None
    employment_type: str
    work_city: str
    jd: str = Field(min_length=1)
    summary: str | None = Field(default=None, max_length=500)
    skills: list[str] = []
    salary_min: int | None = Field(default=None, ge=0)
    salary_max: int | None = Field(default=None, ge=0)
    salary_type: str | None = None
    headcount: int = Field(default=1, ge=1)
    status: str = "draft"


class RequisitionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    req_no: str
    title: str
    department_id: int | None
    department_name: str | None
    requested_by: int | None
    employment_type: str
    work_city: str
    jd: str
    summary: str | None
    skills: list[str] | None
    salary_min: int | None
    salary_max: int | None
    salary_type: str | None
    headcount: int
    status: str
    published_at: datetime | None
    created_at: datetime


class CandidateResumeSummaryRead(BaseModel):
    id: int
    target_requisition_id: int | None
    target_requisition_title: str | None
    original_filename: str | None
    source_platform: str
    parse_status: str
    resume_url: str | None
    has_file: bool


class CandidateApplicationDetailRead(BaseModel):
    id: int
    requisition_id: int
    status: str
    source: str
    applied_at: datetime
    resume_id: int | None
    cover_letter: str | None
    linkedin_url: str | None
    portfolio_url: str | None
    requisition: RequisitionRead
    resume: CandidateResumeSummaryRead | None


class CandidateDetailRead(CandidateRead):
    current_company: str | None
    highest_education: str | None
    expected_title: str | None
    expected_cities: list[str] | None
    expected_salary_min: int | None
    expected_salary_max: int | None
    salary_type: str | None
    availability: str | None
    job_type: str | None
    summary: str | None
    skills: list[str]
    educations: list[CandidateEducationRead]
    experiences: list[CandidateExperienceRead]
    applications: list[CandidateApplicationDetailRead]
    resumes: list[CandidateResumeSummaryRead]


class RequisitionUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=100)
    department_id: int | None = None
    employment_type: str | None = None
    work_city: str | None = None
    jd: str | None = Field(default=None, min_length=1)
    summary: str | None = Field(default=None, max_length=500)
    skills: list[str] | None = None
    salary_min: int | None = Field(default=None, ge=0)
    salary_max: int | None = Field(default=None, ge=0)
    salary_type: str | None = None
    headcount: int | None = Field(default=None, ge=1)
    status: str | None = None


class DepartmentRequisitionCreate(BaseModel):
    """Fields a department manager may submit for their own department."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=100)
    employment_type: str = Field(default="full_time", min_length=1, max_length=20)
    work_city: str = Field(min_length=1, max_length=50)
    jd: str = Field(min_length=1)
    summary: str | None = Field(default=None, max_length=500)
    skills: list[str] = Field(default_factory=list)
    salary_min: int | None = Field(default=None, ge=0)
    salary_max: int | None = Field(default=None, ge=0)
    salary_type: str | None = Field(default="monthly", max_length=10)
    headcount: int = Field(default=1, ge=1)


class DepartmentApplicantRead(BaseModel):
    application_id: int
    application_status: str
    application_source: str
    applied_at: datetime
    match_score: float | None = None
    match_status: str | None = None
    candidate: CandidateRead


class DepartmentJobWorkspaceRead(BaseModel):
    requisition: RequisitionRead
    applicants: list[DepartmentApplicantRead]


class DepartmentWorkspaceRead(BaseModel):
    department_id: int
    department_name: str
    total_jobs: int
    total_applications: int
    total_candidates: int
    jobs: list[DepartmentJobWorkspaceRead]


class ResumeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    candidate_id: int | None
    target_requisition_id: int | None
    uploaded_by: int | None
    original_filename: str | None
    source_platform: str
    requested_source_platform: str | None
    source_confidence: float | None
    source_evidence: list[dict] | None
    source_review_required: bool
    source_reviewed_by: int | None
    source_reviewed_at: datetime | None
    parse_status: str
    parsed_payload: dict | None
    field_confidence: dict | None
    overall_confidence: float | None
    parser_version: str | None
    error_message: str | None
    resume_text: str | None
    file_hash: str | None
    file_size: int | None
    mime: str | None
    resume_url: str | None
    uploaded_at: datetime
    updated_at: datetime
    confirmed_at: datetime | None


class ResumeParsedUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=100)
    email: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=50)
    city: str | None = Field(default=None, max_length=50)
    current_title: str | None = Field(default=None, max_length=100)
    total_years: float | None = Field(default=None, ge=0, le=80)
    current_company: str | None = Field(default=None, max_length=100)
    highest_education: str | None = Field(default=None, max_length=20)
    expected_title: str | None = Field(default=None, max_length=100)
    expected_cities: list[str] = Field(default_factory=list, max_length=30)
    skills: list[str] = Field(default_factory=list, max_length=100)

    @field_validator("skills")
    @classmethod
    def clean_skills(cls, values: list[str]) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for value in values:
            clean = value.strip()[:100]
            key = clean.casefold()
            if clean and key not in seen:
                result.append(clean)
                seen.add(key)
        return result


class ResumeUploadResult(BaseModel):
    id: int
    original_filename: str
    target_requisition_id: int | None
    source_platform: Literal["direct", "p104", "p1111", "generic"]
    source_confidence: float | None
    source_evidence: list[dict] | None
    source_review_required: bool
    parse_status: str
    duplicate: bool = False


class ResumeConfirmResult(BaseModel):
    resume_id: int
    candidate_id: int
    candidate_code: str
    created: bool


class ResumeConfirmRequest(BaseModel):
    candidate_id: int | None = None


class ResumeSourceReview(BaseModel):
    source_platform: Literal["direct", "p104", "p1111", "generic"]


InterviewResult = Literal[
    "pending",
    "advance",
    "hold",
    "rejected",
    "offered",
    "hired",
    "no_show",
    "cancelled",
]
InterviewStage = Literal["hr", "manager"]


class ApplicationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_id: int = Field(gt=0)
    requisition_id: int = Field(gt=0)


class ApplicationAssignmentUpdate(BaseModel):
    """Move an existing application to the HR-selected target requisition."""

    model_config = ConfigDict(extra="forbid")

    requisition_id: int = Field(gt=0)


class ApplicationInterviewUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    interview_at: datetime | None = None
    interview_result: InterviewResult | None = None
    interview_notes: str | None = Field(default=None, max_length=10000)

    @field_validator("interview_at")
    @classmethod
    def require_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("interview_at must include a timezone offset")
        return value

    @model_validator(mode="after")
    def require_update_field(self):
        if not self.model_fields_set:
            raise ValueError("At least one interview field is required")
        return self


class ApplicationInterviewStageRead(BaseModel):
    stage: InterviewStage
    interview_at: datetime | None
    interview_result: InterviewResult | None
    interview_notes: str | None
    updated_by: int | None
    updated_at: datetime | None


class ApplicationRead(BaseModel):
    id: int
    candidate_id: int
    requisition_id: int
    status: str
    source: str
    applied_at: datetime
    resume_id: int | None
    cover_letter: str | None
    linkedin_url: str | None
    portfolio_url: str | None
    interview_at: datetime | None
    interview_result: InterviewResult | None
    interview_notes: str | None
    hr_interview: ApplicationInterviewStageRead
    manager_interview: ApplicationInterviewStageRead
    candidate: CandidateRead
    requisition: RequisitionRead
