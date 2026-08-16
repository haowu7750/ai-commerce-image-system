from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


DesignTaskStatus = Literal[
    "assigned",
    "viewed",
    "in_progress",
    "needs_information",
    "submitted",
    "rework",
    "completed",
    "cancelled",
]


class DesignTaskCreate(BaseModel):
    project_id: str
    assigned_to_id: str
    title: str = Field(min_length=1, max_length=200)
    brief: str = Field(min_length=10, max_length=10000)
    requirements: list[dict[str, Any]] = Field(default_factory=list)
    priority: Literal["low", "normal", "high", "urgent"] = "normal"
    due_at: datetime | None = None


class DesignTaskStatusUpdate(BaseModel):
    status: Literal["viewed", "in_progress", "needs_information"]
    note: str | None = Field(default=None, max_length=2000)


class DesignSubmissionCreate(BaseModel):
    file_url: str = Field(min_length=1, max_length=2_000_000)
    notes: str = Field(default="", max_length=5000)


class DesignReviewCreate(BaseModel):
    decision: Literal["accepted", "partial", "rework"]
    notes: str = Field(min_length=2, max_length=5000)


class DesignTaskCancel(BaseModel):
    reason: str = Field(min_length=2, max_length=2000)


class DesignSubmissionView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    task_id: str
    submitted_by_id: str
    version_no: int
    file_url: str
    notes: str
    created_at: datetime


class DesignTaskView(BaseModel):
    id: str
    project_id: str
    project_name: str
    product_name: str | None
    created_by_id: str
    assigned_to_id: str
    assigned_to_name: str
    title: str
    brief: str
    requirements: list[dict[str, Any]]
    priority: str
    status: DesignTaskStatus
    due_at: datetime | None
    review_notes: str | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime
    submissions: list[DesignSubmissionView]


SystemResourceKind = Literal[
    "prompt",
    "compliance_rule",
    "erp_connection",
    "system_setting",
]


class SystemResourceCreate(BaseModel):
    kind: SystemResourceKind
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=5000)
    content: dict[str, Any] = Field(default_factory=dict)
    is_active: bool = True


class SystemResourceUpdate(BaseModel):
    description: str | None = Field(default=None, max_length=5000)
    content: dict[str, Any] | None = None
    is_active: bool | None = None


class SystemResourceView(BaseModel):
    id: str
    kind: str
    name: str
    description: str
    content: dict[str, Any]
    version: int
    is_active: bool
    updated_by_id: str
    created_at: datetime
    updated_at: datetime


class AuditEventView(BaseModel):
    id: str
    actor_id: str | None
    project_id: str | None
    action: str
    object_type: str
    object_id: str | None
    request_id: str | None
    payload_summary: dict[str, Any]
    result: str
    created_at: datetime
