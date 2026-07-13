from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class UserCreate(BaseModel):
    username: str = Field(min_length=2, max_length=100)
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=12, max_length=1024)
    display_name: str = Field(min_length=1, max_length=100)
    role: Literal["admin", "hr", "manager"]
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
    display_name: str | None = Field(default=None, min_length=1, max_length=100)
    role: Literal["admin", "hr", "manager"] | None = None
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
