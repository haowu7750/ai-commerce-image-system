from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


RiskLevel = Literal["none", "low", "medium", "high"]
ContentAiOperation = Literal[
    "image_analysis",
    "title_generation",
    "sku_generation",
    "compliance_check",
]


class StrictSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ContentAiTrace(StrictSchema):
    content_version_id: str
    project_id: str
    version_no: int
    operation: ContentAiOperation
    provider: Literal["deterministic_mock"] = "deterministic_mock"
    model: str
    prompt_version: str
    rule_version: str
    input_digest: str
    product_card_revision: int | None
    generated_by_id: str
    generated_at: datetime
    network_used: Literal[False] = False
    status: Literal["ai_draft"] = "ai_draft"
    is_final: Literal[False] = False


class ImageAnalysisRequest(StrictSchema):
    selected_asset_ids: list[str] = Field(min_length=1, max_length=5)
    operator_ocr_texts: list[str] = Field(default_factory=list, max_length=20)


class AnalysisPoint(StrictSchema):
    code: str
    text: str
    evidence: str
    source_asset_ids: list[str] = Field(default_factory=list)


class ImageAnalysisResponse(StrictSchema):
    trace: ContentAiTrace
    facts: list[AnalysisPoint]
    judgments: list[AnalysisPoint]
    suggestions: list[AnalysisPoint]
    uncertainties: list[AnalysisPoint]
    mock_limitations: list[str]


class TitleGenerationRequest(StrictSchema):
    keywords: list[str] = Field(default_factory=list, max_length=20)
    required_words: list[str] = Field(default_factory=list, max_length=10)
    forbidden_words: list[str] = Field(default_factory=list, max_length=20)
    candidate_count: int = Field(default=5, ge=3, le=8)
    target_length: int = Field(default=30, ge=8, le=80)


class TitleRisk(StrictSchema):
    code: str
    level: RiskLevel
    original_text: str
    reason: str
    suggestion: str


class TitleCandidate(StrictSchema):
    candidate_id: str
    text: str
    char_count: int
    keywords: list[str]
    strategy: str
    evidence_terms: list[str]
    risks: list[TitleRisk]
    risk_level: RiskLevel
    can_confirm: bool


class ExcludedTerm(StrictSchema):
    term: str
    reason: str


class TitleGenerationResponse(StrictSchema):
    trace: ContentAiTrace
    candidates: list[TitleCandidate]
    excluded_terms: list[ExcludedTerm]
    warnings: list[str]
    overall_risk: RiskLevel
    high_risk_blocked: bool


JsonScalar = str | int | float | bool | None


class SkuItemInput(StrictSchema):
    item_id: str = Field(min_length=1, max_length=100)
    external_sku_id: str | None = Field(default=None, max_length=200)
    merchant_code: str | None = Field(default=None, max_length=200)
    original_name: str = Field(min_length=1, max_length=300)
    attributes: dict[str, str] = Field(default_factory=dict)
    price: JsonScalar = None
    stock: JsonScalar = None


class SkuGenerationRequest(StrictSchema):
    items: list[SkuItemInput] = Field(min_length=1, max_length=100)
    naming_order: list[str] = Field(default_factory=list, max_length=20)
    separator: str = Field(default=" / ", min_length=1, max_length=5)
    max_length: int = Field(default=40, ge=4, le=120)
    abbreviations: dict[str, str] = Field(default_factory=dict)


class SkuIssue(StrictSchema):
    code: str
    level: Literal["warning", "blocking"]
    message: str
    related_item_ids: list[str] = Field(default_factory=list)


class SkuProtectedFields(StrictSchema):
    external_sku_id: str | None
    merchant_code: str | None
    price: JsonScalar
    stock: JsonScalar


class SkuSuggestion(StrictSchema):
    item_id: str
    original_name: str
    proposed_display_name: str
    attributes: dict[str, str]
    protected: SkuProtectedFields
    issues: list[SkuIssue]
    can_confirm: bool


class SkuGenerationResponse(StrictSchema):
    trace: ContentAiTrace
    suggestions: list[SkuSuggestion]
    batch_issues: list[SkuIssue]
    protected_fields: list[str]
    protected_fields_unchanged: bool
    can_confirm_batch: bool


class ComplianceSegment(StrictSchema):
    segment_id: str = Field(min_length=1, max_length=100)
    text: str = Field(min_length=1, max_length=5000)


class ComplianceCheckRequest(StrictSchema):
    content_type: Literal["title", "sku", "image_ocr", "selling_point", "design_brief"]
    segments: list[ComplianceSegment] = Field(min_length=1, max_length=100)


class ComplianceIssue(StrictSchema):
    issue_id: str
    segment_id: str
    original_text: str
    start: int
    end: int
    level: Literal["low", "medium", "high"]
    code: str
    reason: str
    suggestion: str
    detector: Literal["deterministic_lexicon"] = "deterministic_lexicon"
    rule_source: str


class ComplianceSummary(StrictSchema):
    low: int
    medium: int
    high: int


class ComplianceCheckResponse(StrictSchema):
    trace: ContentAiTrace
    content_type: str
    issues: list[ComplianceIssue]
    summary: ComplianceSummary
    overall_risk: RiskLevel
    high_risk_blocked: bool
    requires_operator_action: bool
    can_finalize: bool
    disclaimer: str


class ContentAiHistoryItem(StrictSchema):
    id: str
    project_id: str
    operation: ContentAiOperation
    version_no: int
    content: dict[str, Any]
    provider: str
    model: str
    prompt_version: str
    rule_version: str
    input_digest: str
    product_card_revision: int | None
    created_by_id: str
    created_at: datetime
    status: str
    is_final: bool
