from datetime import date, datetime
from math import isfinite
from typing import Literal

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

REQUISITION_STATUSES = (
    "draft",
    "submitted",
    "returned",
    "approved",
    "sourcing",
    "interviewing",
    "filled",
    "closed",
)
# Legal requisition status transitions (single source of truth for the approval
# workflow). Every key and value is a member of REQUISITION_STATUSES; "closed" is
# terminal. Enforced by both the PATCH and approve endpoints so the workflow and
# its timestamp side-effects cannot be bypassed by a direct status jump.
ALLOWED_REQUISITION_TRANSITIONS: dict[str, frozenset[str]] = {
    "draft": frozenset({"submitted", "approved", "closed"}),
    "submitted": frozenset({"approved", "returned", "closed"}),
    "returned": frozenset({"draft", "submitted", "approved", "closed"}),
    "approved": frozenset({"sourcing", "interviewing", "filled", "closed"}),
    "sourcing": frozenset({"interviewing", "filled", "closed"}),
    "interviewing": frozenset({"sourcing", "filled", "closed"}),
    "filled": frozenset({"closed"}),
    "closed": frozenset(),
}
# Keys accepted in job_requisitions.composite_score_weights. Kept as a literal
# tuple rather than imported from the service so the schema layer stays free of
# service imports; services.interview_scoring owns the default values and the
# normalisation, and its COMPOSITE_WEIGHT_KEYS is asserted equal to this in tests.
COMPOSITE_SCORE_WEIGHT_KEYS = (
    "resume",
    "hr_questions",
    "hr_overall",
    "manager_questions",
    "manager_overall",
)
CANDIDATE_STATUSES = (
    "new",
    "contacted",
    "priority",
    "interviewing",
    "hired",
    "declined",
    "withdrawn",
    "archived",
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
    retention_years_override: int | None
    retention_until: date | None
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

    @field_validator("status")
    @classmethod
    def validate_status(cls, value: str | None) -> str | None:
        if value is not None and value not in CANDIDATE_STATUSES:
            raise ValueError("未知的人才狀態")
        return value


class CandidateActivityCreate(BaseModel):
    type: str = Field(
        min_length=1, max_length=20, validation_alias=AliasChoices("type", "activity_type")
    )
    content: str = Field(
        min_length=1, max_length=10000, validation_alias=AliasChoices("content", "note")
    )
    happened_at: datetime | None = None
    next_status: str | None = Field(default=None, max_length=20)

    @field_validator("next_status")
    @classmethod
    def validate_next_status(cls, value: str | None) -> str | None:
        if value is not None and value not in CANDIDATE_STATUSES:
            raise ValueError("未知的人才狀態")
        return value


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
    # Only HR may open a requisition with blind review already switched off, same
    # rule the route enforces on RequisitionUpdate. None means "no decision in this
    # request", which leaves the model default (blind review on) in place -- the
    # column is NOT NULL, so an explicit null cannot be stored either way.
    blind_review_enabled: bool | None = None

    @field_validator("status")
    @classmethod
    def validate_status(cls, value: str) -> str:
        if value not in REQUISITION_STATUSES:
            raise ValueError("未知的需求單狀態")
        return value


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
    # Blind review policy for this requisition's two-stage interview. Read by anyone
    # who may read the requisition; blind_review_locked is derived (never written)
    # and turns true once any interview here has been submitted.
    blind_review_enabled: bool
    blind_review_locked: bool
    # Configured composite weights, or null when this requisition uses the
    # defaults. composite_score_weights_resolved is derived and read-only: the
    # same numbers rescaled to sum 1, which is what a composite is actually
    # computed with, so no client has to reimplement the normalisation.
    composite_score_weights: dict[str, float] | None
    composite_score_weights_resolved: dict[str, float]
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
    document_origin: Literal["applicant_upload", "system_generated"]


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
    # Only HR may change this, and only before scoring starts; both rules are
    # enforced by the route. None means "no decision in this request".
    blind_review_enabled: bool | None = None
    # Composite score weights. Only HR may change them (enforced by the route).
    # A partial dict overrides only the keys it names; an explicit null resets the
    # requisition to the built-in defaults. Absent from the request means "no
    # decision", which is why this needs the sentinel below rather than None.
    composite_score_weights: dict[str, float] | None = None

    @field_validator("status")
    @classmethod
    def validate_status(cls, value: str | None) -> str | None:
        if value is not None and value not in REQUISITION_STATUSES:
            raise ValueError("未知的需求單狀態")
        return value

    @field_validator("composite_score_weights")
    @classmethod
    def validate_composite_score_weights(
        cls,
        value: dict[str, float] | None,
    ) -> dict[str, float] | None:
        if value is None:
            return None
        unknown = sorted(set(value) - set(COMPOSITE_SCORE_WEIGHT_KEYS))
        if unknown:
            raise ValueError(f"未知的綜合評分權重項目：{'、'.join(unknown)}")
        for key, weight in value.items():
            # A negative weight would subtract a candidate's score from their own
            # total, and an infinite or NaN one would poison every composite the
            # requisition ever produces.
            if not isfinite(weight) or weight < 0:
                raise ValueError(f"綜合評分權重「{key}」必須為 0 或正數")
        # An all-zero set is not rejected here: resolve_composite_weights treats a
        # non-positive total as carrying no decision and falls back to the
        # defaults, exactly as resolve_weights does for match_weights, and the
        # requisition read shows the resolved weights so the fallback is visible.
        return value


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
    document_origin: Literal["applicant_upload", "system_generated"]
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
    # The sixth score. Null both before the two interview stages are submitted and
    # when nothing could be scored at all; composite_score_breakdown tells those
    # apart -- it is null only while no composite has ever been computed, and
    # otherwise carries a "status" of "pending_stages" or "computed" alongside each
    # component's value, the weight applied to it and the missing-component list.
    composite_score: float | None
    composite_score_breakdown: dict | None
    candidate: CandidateRead
    requisition: RequisitionRead
