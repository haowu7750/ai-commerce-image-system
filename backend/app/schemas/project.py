from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.enums import ProjectStatus


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    platform: str = Field(default="拼多多", min_length=1, max_length=64)
    store_name: str = Field(min_length=1, max_length=200)
    category: str | None = Field(default=None, max_length=200)


class ProjectUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=200)
    platform: str | None = Field(default=None, min_length=1, max_length=64)
    store_name: str | None = Field(default=None, min_length=1, max_length=200)
    category: str | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def require_changed_field(self) -> "ProjectUpdate":
        if not self.model_fields_set:
            raise ValueError("At least one project field is required")
        for field in ("name", "platform", "store_name"):
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null")
        return self


class ProjectDeletionRequest(BaseModel):
    reason: str = Field(min_length=2, max_length=500)


class ProjectView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    created_by_id: str
    name: str
    platform: str
    store_name: str
    category: str | None
    source: str
    status: ProjectStatus
    archived_at: datetime | None
    deleted_by_id: str | None = None
    deletion_reason: str | None = None
    status_before_delete: str | None = None
    created_at: datetime
    updated_at: datetime
