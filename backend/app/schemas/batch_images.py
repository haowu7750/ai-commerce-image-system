from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.enums import (
    BatchImageItemStatus,
    BatchImageMode,
    BatchImageTaskStatus,
    ImageComplianceStatus,
    ImageQaStatus,
)


class BatchImageTaskCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str
    mode: BatchImageMode
    product_reference_asset_ids: list[str] = Field(default_factory=list, max_length=3)
    source_asset_ids: list[str] = Field(min_length=1, max_length=10)
    secondary_asset_ids: list[str] = Field(default_factory=list, max_length=10)
    instruction: str = Field(default="", max_length=2000)
    size: str = Field(default="1024x1024", pattern=r"^\d{2,4}x\d{2,4}$")
    category: str = Field(default="通用类目", min_length=1, max_length=100)
    print_carrier: str | None = Field(default=None, max_length=100)
    subject: str | None = Field(default=None, max_length=100)
    overall_count: int = Field(default=1, ge=0, le=8)
    detail_count: int = Field(default=0, ge=0, le=8)
    idempotency_key: str = Field(min_length=8, max_length=128)

    @model_validator(mode="after")
    def validate_mode_inputs(self) -> BatchImageTaskCreate:
        if self.mode == BatchImageMode.CUSTOM_EDIT and not self.instruction.strip():
            raise ValueError("自定义批量改图必须填写修改说明")
        if self.mode in {
            BatchImageMode.SCENE_REPLACE,
            BatchImageMode.BUYER_SHOW,
            BatchImageMode.REPLACE_PRODUCT,
        } and len(self.product_reference_asset_ids) != 1:
            raise ValueError("场景替换和买家秀必须选择 1 张商品参考图")
        if self.mode == BatchImageMode.PATTERN_EXTRACT and not (
            self.print_carrier or ""
        ).strip():
            raise ValueError("批量印花提取必须选择印花载体")
        if self.mode == BatchImageMode.ANGLE_FISSION:
            if not (self.subject or "").strip():
                raise ValueError("角度裂变必须填写拍摄主体")
            if self.overall_count + self.detail_count < 1:
                raise ValueError("整体图和细节图合计至少生成 1 张")
            if len(self.source_asset_ids) > 5:
                raise ValueError("角度裂变最多上传 5 张产品场景图")
        if self.secondary_asset_ids and self.mode != BatchImageMode.CUSTOM_EDIT:
            raise ValueError("只有自定义批量支持参考图二")
        if self.secondary_asset_ids and len(self.secondary_asset_ids) != len(
            self.source_asset_ids
        ):
            raise ValueError("参考图二必须与参考图一逐张配对，数量需要一致")
        width_text, height_text = self.size.split("x", 1)
        width, height = int(width_text), int(height_text)
        if not (64 <= width <= 4096 and 64 <= height <= 4096):
            raise ValueError("输出尺寸必须在 64x64 到 4096x4096 之间")
        if len(set(self.product_reference_asset_ids)) != len(
            self.product_reference_asset_ids
        ):
            raise ValueError("商品参考图不能重复")
        if len(set(self.source_asset_ids)) != len(self.source_asset_ids):
            raise ValueError("待处理图片不能重复")
        if len(set(self.secondary_asset_ids)) != len(self.secondary_asset_ids):
            raise ValueError("参考图二不能重复")
        return self


class BatchImageTaskSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_ids: list[str] = Field(min_length=1, max_length=50)


class BatchImageItemReview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=1)
    product_facts_match: bool
    geometry_and_count_match: bool
    logo_text_and_personalization_match: bool
    thumbnail_readable: bool
    compliance_risk: str = Field(pattern="^(clear|medium|high)$")
    notes: str = Field(min_length=10, max_length=3000)
    retain_medium_risk_reason: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def validate_medium_risk_reason(self) -> BatchImageItemReview:
        if self.compliance_risk == "medium":
            reason = (self.retain_medium_risk_reason or "").strip()
            if len(reason) < 10:
                raise ValueError("中风险结果必须填写至少 10 个字的保留理由")
        return self


class BatchImageItemConfirm(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=1)


class BatchImageItemView(BaseModel):
    id: str
    task_id: str
    source_asset_id: str | None
    output_asset_id: str | None
    position: int
    status: BatchImageItemStatus
    error_code: str | None
    error_message: str | None
    output_mime_type: str | None
    provider_url: str | None
    preview_data_url: str | None
    revised_prompt: str | None
    metadata: dict[str, object]
    qa_status: ImageQaStatus
    compliance_status: ImageComplianceStatus
    review_report: dict[str, object]
    reviewed_by_id: str | None
    reviewed_at: datetime | None
    confirmed_by_id: str | None
    confirmed_at: datetime | None
    revision: int


class BatchImageTaskView(BaseModel):
    id: str
    project_id: str
    created_by_id: str
    mode: BatchImageMode
    status: BatchImageTaskStatus
    provider: str
    model: str
    prompt: str
    options: dict[str, object]
    product_reference_asset_ids: list[str]
    source_asset_ids: list[str]
    is_archived: bool
    progress_total: int
    progress_done: int
    succeeded_count: int
    failed_count: int
    error_code: str | None
    error_message: str | None
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime
    updated_at: datetime
    items: list[BatchImageItemView]
