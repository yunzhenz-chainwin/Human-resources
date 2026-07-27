from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class UserCreate(BaseModel):
    username: str = Field(min_length=2, max_length=100)
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=12, max_length=1024)
    display_name: str = Field(min_length=1, max_length=100)
    role: Literal["admin", "it", "hr", "manager"]
    department_id: int | None = None

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        normalized = value.strip().lower()
        if "@" not in normalized or normalized.startswith("@") or normalized.endswith("@"):
            raise ValueError("Invalid email")
        return normalized


class UserUpdate(BaseModel):
    email: str | None = Field(default=None, min_length=3, max_length=255)
    password: str | None = Field(default=None, min_length=12, max_length=1024)
    password_confirm: str | None = Field(default=None, min_length=12, max_length=1024)
    display_name: str | None = Field(default=None, min_length=1, max_length=100)
    role: Literal["admin", "it", "hr", "manager"] | None = None
    department_id: int | None = None
    is_active: bool | None = None

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().lower()
        if "@" not in normalized or normalized.startswith("@") or normalized.endswith("@"):
            raise ValueError("Invalid email")
        return normalized


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    username: str
    email: str
    display_name: str
    role: str
    department_id: int | None
    is_active: bool
    created_at: datetime
    updated_at: datetime
    last_login_at: datetime | None = None
    password_changed_at: datetime | None = None


class TemporaryPasswordResetRead(BaseModel):
    user_id: int
    username: str
    temporary_password: str
    password_changed_at: datetime
    sessions_revoked: int = 0


class DepartmentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    parent_id: int | None = None


class DepartmentUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    parent_id: int | None = None
    is_active: bool | None = None


class DepartmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    parent_id: int | None
    is_active: bool


class CatalogCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    category: str = Field(default="candidate", max_length=50)


class CatalogRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    category: str | None = None
    is_active: bool


class SettingWrite(BaseModel):
    value: Any = None
    description: str | None = Field(default=None, max_length=255)
    is_secret: bool = False


class SettingRead(BaseModel):
    key: str
    value: Any = None
    description: str | None
    is_secret: bool


class AuditRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    actor_user_id: int | None
    action: str
    resource_type: str
    resource_id: str | None
    department_id: int | None
    details: dict | None
    ip_address: str | None
    created_at: datetime


IssueSeverity = Literal["low", "medium", "high", "critical"]
IssueStatus = Literal["open", "investigating", "resolved", "closed"]
IssueCategory = Literal["feature", "optimization", "bug", "maintenance", "other"]


class SystemIssueCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=10000)
    page: str = Field(min_length=1, max_length=255)
    category: IssueCategory = "other"
    severity: IssueSeverity = "medium"
    status: IssueStatus = "open"
    progress_percent: int = Field(default=0, ge=0, le=100)
    expected_completion_date: date | None = None
    reproduction_steps: str | None = Field(default=None, max_length=20000)
    resolution_notes: str | None = Field(default=None, max_length=20000)


class SystemIssueUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, min_length=1, max_length=10000)
    page: str | None = Field(default=None, min_length=1, max_length=255)
    category: IssueCategory | None = None
    severity: IssueSeverity | None = None
    status: IssueStatus | None = None
    progress_percent: int | None = Field(default=None, ge=0, le=100)
    expected_completion_date: date | None = None
    reproduction_steps: str | None = Field(default=None, max_length=20000)
    resolution_notes: str | None = Field(default=None, max_length=20000)


class SystemIssueRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    title: str
    description: str
    page: str
    category: str
    severity: str
    status: str
    progress_percent: int
    expected_completion_date: date | None
    reproduction_steps: str | None
    resolution_notes: str | None
    created_by_user_id: int | None
    updated_by_user_id: int | None
    created_at: datetime
    updated_at: datetime


class DatabaseColumnRead(BaseModel):
    name: str
    type: str
    nullable: bool
    primary_key: bool
    redacted: bool = False
    revealable: bool = False
    editable: bool = False


class DatabaseTableRead(BaseModel):
    name: str
    display_name: str
    description: str
    row_count: int | None
    columns: list[DatabaseColumnRead]
    can_create: bool = False
    can_update: bool = False
    can_delete: bool = False
    editable_columns: list[str] = Field(default_factory=list)
    protection_reason: str | None = None


class DatabaseOverviewRead(BaseModel):
    healthy: bool
    dialect: str
    server_version: str | None
    transport_security: str
    tables: list[DatabaseTableRead]


class DatabaseTablePreviewRead(BaseModel):
    table_name: str
    display_name: str
    description: str
    page: int
    page_size: int
    total: int
    searchable_columns: list[str]
    visible_columns: list[str]
    redacted_columns: list[str]
    pii_revealed: bool = False
    rows: list[dict[str, Any]]


class DatabaseRowDetailRead(BaseModel):
    table_name: str
    display_name: str
    row_id: int | str
    pii_revealed: bool = False
    redacted_columns: list[str]
    row: dict[str, Any]
    related: dict[str, Any] = Field(default_factory=dict)


class DatabaseRowWrite(BaseModel):
    values: dict[str, Any] = Field(min_length=1, max_length=100)


class DatabaseRowMutationRead(BaseModel):
    table_name: str
    row_id: int | str
    row: dict[str, Any] | None = None
