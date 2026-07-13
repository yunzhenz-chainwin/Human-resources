from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator


class PublicJob(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    req_no: str
    title: str
    department: str | None
    location: str
    employment_type: str
    summary: str
    jd: str
    skills: list[str] = []
    salary_min: int | None
    salary_max: int | None
    salary_type: str | None
    status: str
    published_at: datetime | None


class PublicApplicationCreate(BaseModel):
    requisition_id: int
    name: str = Field(min_length=1, max_length=100)
    email: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, min_length=8, max_length=50)
    city: str | None = Field(default=None, max_length=50)
    current_title: str | None = Field(default=None, max_length=100)
    total_years: float | None = Field(default=None, ge=0, le=80)
    cover_letter: str | None = Field(default=None, max_length=10000)
    linkedin_url: HttpUrl | None = None
    portfolio_url: HttpUrl | None = None
    resume_url: HttpUrl | None = None
    resume_text: str | None = Field(default=None, max_length=100000)
    consent: bool

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str | None) -> str | None:
        if value and ("@" not in value or "." not in value.rsplit("@", 1)[-1]):
            raise ValueError("Invalid email address")
        return value

    @model_validator(mode="after")
    def validate_contact_and_consent(self):
        if not self.email and not self.phone:
            raise ValueError("Email or phone is required")
        if not self.consent:
            raise ValueError("Consent is required")
        return self


class PublicApplicationResult(BaseModel):
    application_id: int
    status: str
    duplicate: bool


class PublicTalentPoolResult(BaseModel):
    resume_id: int
    status: str
    duplicate: bool
