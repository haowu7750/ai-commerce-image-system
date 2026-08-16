"""Vendor-neutral ERP adapter contracts and the local Mock ERP implementation."""

from app.erp.base import ERPConnector, ERPConnectorCapabilities, UnifiedProduct
from app.erp.mock import MockERPConnector

__all__ = [
    "ERPConnector",
    "ERPConnectorCapabilities",
    "MockERPConnector",
    "UnifiedProduct",
]
