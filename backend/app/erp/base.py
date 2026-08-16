from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Literal

from pydantic import BaseModel, Field


class ERPConnectorCapabilities(BaseModel):
    connector_key: str
    display_name: str
    mode: Literal["mock", "real"]
    can_import_products: bool
    can_refresh_products: bool
    can_write_drafts: bool
    can_publish: bool
    supports_external_version_check: bool
    supports_idempotency: bool
    writable_targets: list[str]
    protected_fields: list[str]
    notes: list[str] = Field(default_factory=list)


class UnifiedImage(BaseModel):
    url: str
    kind: Literal["product", "main", "sku", "reference"] = "product"
    alt: str | None = None


class UnifiedSku(BaseModel):
    """Canonical SKU data.

    Merchant codes, price and inventory are deliberately read-only. They can be
    imported for operator context, but the write-back builder always removes them.
    """

    source_code: str | None = None
    option_values: dict[str, str] = Field(default_factory=dict)
    display_name: str | None = None
    price: float | None = None
    inventory: int | None = None


class UnifiedProduct(BaseModel):
    external_id: str
    external_version: str
    name: str
    brand: str | None = None
    title: str | None = None
    category: str | None = None
    facts: dict[str, Any] = Field(default_factory=dict)
    selling_points: list[dict[str, Any]] = Field(default_factory=list)
    specs: list[dict[str, Any]] = Field(default_factory=list)
    skus: list[UnifiedSku] = Field(default_factory=list)
    images: list[UnifiedImage] = Field(default_factory=list)
    source_snapshot: dict[str, Any] = Field(default_factory=dict)


class ERPConnector(ABC):
    """Stable vendor-neutral contract used by the core application."""

    @abstractmethod
    def capabilities(self) -> ERPConnectorCapabilities:
        raise NotImplementedError

    @abstractmethod
    def list_products(self) -> list[UnifiedProduct]:
        raise NotImplementedError

    @abstractmethod
    def get_product(self, external_id: str) -> UnifiedProduct | None:
        raise NotImplementedError

    @abstractmethod
    def write_draft(
        self,
        *,
        external_id: str,
        expected_external_version: str,
        payload: dict[str, Any],
        idempotency_key: str,
    ) -> tuple[str, dict[str, Any]]:
        """Write only to a draft area and return (new_external_version, snapshot)."""

        raise NotImplementedError
