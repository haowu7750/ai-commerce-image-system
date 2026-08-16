from __future__ import annotations

from copy import deepcopy
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.erp.base import ERPConnector, ERPConnectorCapabilities, UnifiedProduct
from app.models.erp import MockERPProduct


DEFAULT_FIELD_MAPPING: dict[str, str] = {
    "external_id": "mockItemId",
    "external_version": "mockVersion",
    "name": "itemName",
    "brand": "brandName",
    "title": "listingTitle",
    "category": "categoryName",
    "facts": "factData",
    "selling_points": "sellingPointRows",
    "specs": "specRows",
    "skus": "mockSkuRows",
    "images": "mockImageRows",
}


MOCK_PRODUCTS: tuple[dict[str, Any], ...] = (
    {
        "mockItemId": "MOCK-PROD-001",
        "mockVersion": 1,
        "itemName": "便携式桌面补光灯",
        "brandName": "演示品牌",
        "listingTitle": "便携式桌面补光灯 可调亮度",
        "categoryName": "数码配件",
        "factData": {"material": "ABS", "color": "白色", "power": "USB"},
        "sellingPointRows": [
            {"text": "三档亮度可调", "source": "mock_erp"},
            {"text": "折叠便携", "source": "mock_erp"},
        ],
        "specRows": [{"name": "尺寸", "value": "16cm"}],
        "mockSkuRows": [
            {
                "source_code": "READONLY-DEMO-WHITE",
                "option_values": {"颜色": "白色"},
                "display_name": "白色款",
                "price": 39.9,
                "inventory": 25,
            }
        ],
        "mockImageRows": [],
    },
    {
        "mockItemId": "MOCK-PROD-002",
        "mockVersion": 1,
        "itemName": "厨房硅胶沥水垫",
        "brandName": None,
        "listingTitle": "厨房硅胶沥水垫 防滑耐用",
        "categoryName": "厨房用品",
        "factData": {"material": "硅胶", "color": "灰色"},
        "sellingPointRows": [{"text": "易清洁", "source": "mock_erp"}],
        "specRows": [{"name": "尺寸", "value": "40x30cm"}],
        "mockSkuRows": [],
        "mockImageRows": [],
    },
)


def _read_path(payload: dict[str, Any], path: str) -> Any:
    value: Any = payload
    for part in path.split("."):
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    return value


def normalize_product(
    raw_payload: dict[str, Any], mapping: dict[str, str] | None = None
) -> UnifiedProduct:
    active_mapping = mapping or DEFAULT_FIELD_MAPPING
    values = {
        field: _read_path(raw_payload, path)
        for field, path in active_mapping.items()
    }
    values.setdefault("facts", {})
    values.setdefault("selling_points", [])
    values.setdefault("specs", [])
    values.setdefault("skus", [])
    values.setdefault("images", [])
    values["external_version"] = str(values.get("external_version") or "")
    values["source_snapshot"] = {
        "connector": "mock",
        "mapped_fields": sorted(active_mapping),
    }
    return UnifiedProduct.model_validate(values)


class MockERPConnector(ERPConnector):
    """Persistent local-only ERP simulation. This class performs no network I/O."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def ensure_seed_data(self) -> None:
        for payload in MOCK_PRODUCTS:
            external_id = str(payload["mockItemId"])
            existing = self.db.scalar(
                select(MockERPProduct).where(MockERPProduct.external_id == external_id)
            )
            if existing is None:
                self.db.add(
                    MockERPProduct(
                        external_id=external_id,
                        external_version=int(payload["mockVersion"]),
                        raw_payload_json=deepcopy(payload),
                        published=False,
                    )
                )
        self.db.flush()

    def capabilities(self) -> ERPConnectorCapabilities:
        return ERPConnectorCapabilities(
            connector_key="mock",
            display_name="本地 Mock ERP",
            mode="mock",
            can_import_products=True,
            can_refresh_products=True,
            can_write_drafts=True,
            can_publish=False,
            supports_external_version_check=True,
            supports_idempotency=True,
            writable_targets=["draft"],
            protected_fields=[
                "price",
                "inventory",
                "stock",
                "merchant_code",
                "seller_sku",
                "sku_code",
                "source_code",
            ],
            notes=[
                "仅用于本地契约验证，不连接任何真实 ERP",
                "写回只进入 Mock 草稿区，永不发布",
            ],
        )

    def _row_to_product(
        self, row: MockERPProduct, mapping: dict[str, str] | None = None
    ) -> UnifiedProduct:
        raw = deepcopy(row.raw_payload_json)
        raw["mockVersion"] = row.external_version
        return normalize_product(raw, mapping)

    def list_products(self) -> list[UnifiedProduct]:
        self.ensure_seed_data()
        rows = self.db.scalars(
            select(MockERPProduct).order_by(MockERPProduct.external_id)
        ).all()
        return [self._row_to_product(row) for row in rows]

    def get_product(self, external_id: str) -> UnifiedProduct | None:
        self.ensure_seed_data()
        row = self.db.scalar(
            select(MockERPProduct).where(MockERPProduct.external_id == external_id)
        )
        return self._row_to_product(row) if row is not None else None

    def get_product_with_mapping(
        self, external_id: str, mapping: dict[str, str]
    ) -> UnifiedProduct | None:
        self.ensure_seed_data()
        row = self.db.scalar(
            select(MockERPProduct).where(MockERPProduct.external_id == external_id)
        )
        return self._row_to_product(row, mapping) if row is not None else None

    def write_draft(
        self,
        *,
        external_id: str,
        expected_external_version: str,
        payload: dict[str, Any],
        idempotency_key: str,
    ) -> tuple[str, dict[str, Any]]:
        row = self.db.scalar(
            select(MockERPProduct).where(MockERPProduct.external_id == external_id)
        )
        if row is None:
            raise KeyError("External Mock ERP product not found")
        if row.last_idempotency_key == idempotency_key:
            return str(row.external_version), deepcopy(row.draft_payload_json)
        if str(row.external_version) != str(expected_external_version):
            raise ValueError("External version conflict")
        row.draft_payload_json = deepcopy(payload)
        row.external_version += 1
        row.last_idempotency_key = idempotency_key
        row.published = False
        self.db.flush()
        return str(row.external_version), deepcopy(row.draft_payload_json)

    def simulate_external_change(self, external_id: str) -> str:
        row = self.db.scalar(
            select(MockERPProduct).where(MockERPProduct.external_id == external_id)
        )
        if row is None:
            raise KeyError("External Mock ERP product not found")
        row.external_version += 1
        raw = deepcopy(row.raw_payload_json)
        raw["mockVersion"] = row.external_version
        raw["externalChangeMarker"] = f"simulated-{row.external_version}"
        row.raw_payload_json = raw
        self.db.flush()
        return str(row.external_version)
