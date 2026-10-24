"""Request/response models for the reachability API."""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class ReachabilityStatus(str, Enum):
    REACHABLE = "reachable"
    UNREACHABLE = "unreachable"
    NEEDS_REVIEW = "needs_review"


class Severity(str, Enum):
    INFO = "info"
    WARN = "warn"
    BLOCK = "block"


class AddressInput(BaseModel):
    """Flexible address input. Prefer structured fields; raw alone is OK."""

    country: Optional[str] = Field(
        None, description="ISO 3166-1 alpha-2, e.g. ZA/BR/ID/CO/CN"
    )
    raw: Optional[str] = Field(None, description="Unstructured address line(s)")
    province: Optional[str] = None
    admin1: Optional[str] = Field(None, description="State/province/UF")
    city: Optional[str] = None
    locality: Optional[str] = None
    admin2: Optional[str] = None
    suburb: Optional[str] = None
    road: Optional[str] = None
    house_number: Optional[str] = None
    postal_code: Optional[str] = None
    county: Optional[str] = None
    district: Optional[str] = None
    sample_tag: Optional[str] = Field(
        None, description="Optional fixture tag, e.g. co_bad_geocode"
    )
    # Optional known-bad coords (Colombia dispute demo)
    lat: Optional[float] = None
    lng: Optional[float] = None


class ReachabilityRequest(BaseModel):
    address: AddressInput
    carrier: Optional[str] = Field(
        "sf_express", description="Carrier adapter id for filter stage"
    )
    product_code: Optional[str] = None
    options: dict[str, Any] = Field(default_factory=dict)


class Reason(BaseModel):
    code: str = Field(..., description="Machine-readable reason code")
    message: str = Field(..., description="Human-readable explanation")
    path: str = Field(
        ...,
        description="JSON-path-like pointer, e.g. address.city or stage.geocode",
    )
    severity: Severity = Severity.WARN
    rule_id: Optional[str] = Field(None, description="Matched configurable rule id")
    stage: Optional[str] = None
    details: dict[str, Any] = Field(default_factory=dict)


class ParsedAddress(BaseModel):
    country: Optional[str] = None
    province: Optional[str] = None
    admin1: Optional[str] = None
    city: Optional[str] = None
    locality: Optional[str] = None
    admin2: Optional[str] = None
    suburb: Optional[str] = None
    road: Optional[str] = None
    house_number: Optional[str] = None
    postal_code: Optional[str] = None
    county: Optional[str] = None
    district: Optional[str] = None
    cleaned_raw: Optional[str] = None
    parse_confidence: float = 0.0
    completeness: str = "unknown"  # sufficient | insufficient | unknown


class GeocodeResult(BaseModel):
    lat: Optional[float] = None
    lng: Optional[float] = None
    confidence: float = 0.0
    provider: Optional[str] = None
    coordinate_system: Optional[str] = None
    dispute_km: Optional[float] = None
    candidates: list[dict[str, Any]] = Field(default_factory=list)


class CarrierFilterResult(BaseModel):
    """Aligned with SF EXP_RECE_FILTER_ORDER_BSP filterResult semantics."""

    filter_result: int = Field(
        ...,
        description="1=manual, 2=in service, 3=out of service, 4=addr unconfirmed",
    )
    origin_code: Optional[str] = None
    dest_code: Optional[str] = None
    remark: Optional[str] = None
    carrier: Optional[str] = None


class StageTrace(BaseModel):
    stage: str
    ok: bool
    duration_ms: float = 0.0
    notes: list[str] = Field(default_factory=list)
    data: dict[str, Any] = Field(default_factory=dict)


class ReachabilityResponse(BaseModel):
    status: ReachabilityStatus
    reachable: bool
    deliverability_score: float = Field(..., ge=0, le=100)
    reasons: list[Reason] = Field(default_factory=list)
    parsed: Optional[ParsedAddress] = None
    geocode: Optional[GeocodeResult] = None
    carrier_filter: Optional[CarrierFilterResult] = None
    pipeline: list[StageTrace] = Field(default_factory=list)
    rules_version: Optional[str] = None
    request_id: Optional[str] = None


class HealthResponse(BaseModel):
    status: str
    rules_version: Optional[str] = None
    adapters: dict[str, str] = Field(default_factory=dict)
