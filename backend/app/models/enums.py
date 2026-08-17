from enum import StrEnum


class RoleName(StrEnum):
    OPERATOR = "operator"
    DESIGNER = "designer"
    ADMIN = "admin"


class ProjectStatus(StrEnum):
    DRAFT = "draft"
    NEEDS_INFORMATION = "needs_information"
    IN_PROGRESS = "in_progress"
    WAITING_FOR_DESIGN = "waiting_for_design"
    WAITING_FOR_OPERATOR_REVIEW = "waiting_for_operator_review"
    READY_TO_PUBLISH = "ready_to_publish"
    COMPLETED = "completed"
    ARCHIVED = "archived"


class AssetType(StrEnum):
    PRODUCT_RAW = "product_raw"
    PRODUCT_REFERENCE = "product_reference"
    MAIN_IMAGE = "main_image"
    COMPETITOR_IMAGE = "competitor_image"
    STYLE_REFERENCE = "style_reference"
    SKU_IMAGE = "sku_image"
    DESIGN_RESULT = "design_result"
    GENERATED_IMAGE = "generated_image"


class ContentStatus(StrEnum):
    AI_DRAFT = "ai_draft"
    EDITING = "editing"
    PENDING_COMPLIANCE = "pending_compliance"
    PENDING_OPERATOR_CONFIRMATION = "pending_operator_confirmation"
    FINAL = "final"
    INVALIDATED = "invalidated"


class ImageOperation(StrEnum):
    GENERATION = "generation"
    EDIT = "edit"


class BatchImageMode(StrEnum):
    SCENE_REPLACE = "scene_replace"
    PATTERN_EXTRACT = "pattern_extract"
    CUSTOM_EDIT = "custom_edit"
    RESIZE = "resize"
    BUYER_SHOW = "buyer_show"
    ANGLE_FISSION = "angle_fission"
    # Kept so tasks created by the first supervised-batch release remain readable.
    REPLACE_PRODUCT = "replace_product"


class BatchImageTaskStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    PARTIAL = "partial"
    FAILED = "failed"
    CANCELLED = "cancelled"


class BatchImageItemStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class ImageJobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ImageWorkflowStatus(StrEnum):
    DRAFT = "draft"
    PRODUCT_TYPE_READY = "product_type_ready"
    SCENE_PLAN_READY = "scene_plan_ready"
    HERO_SCENE_SELECTED = "hero_scene_selected"
    PROMPT_READY = "prompt_ready"
    GENERATING = "generating"
    CANDIDATE_READY = "candidate_ready"
    QA_PENDING = "qa_pending"
    QA_FAILED = "qa_failed"
    COMPLIANCE_BLOCKED = "compliance_blocked"
    AWAITING_OPERATOR_CONFIRMATION = "awaiting_operator_confirmation"
    OPERATOR_CONFIRMED = "operator_confirmed"
    GENERATION_FAILED = "generation_failed"
    STALE = "stale"
    CANCELLED = "cancelled"


class ImageQaStatus(StrEnum):
    PENDING = "pending"
    PASSED = "passed"
    FAILED = "failed"
    INVALIDATED = "invalidated"


class ImageComplianceStatus(StrEnum):
    UNCHECKED = "unchecked"
    CHECKING = "checking"
    CLEAR = "clear"
    MEDIUM_OPEN = "medium_open"
    MEDIUM_RESOLVED = "medium_resolved"
    HIGH_OPEN = "high_open"
    INVALIDATED = "invalidated"
