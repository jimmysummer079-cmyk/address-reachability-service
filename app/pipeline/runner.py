"""Orchestrates the address reachability pipeline."""

from __future__ import annotations

import re
import time
import uuid
from typing import Any, Optional

from app.adapters.fengtu_client import FengtuClient
from app.adapters.fengtu_mock import FengtuMockAdapter
from app.adapters.intl_mock import GenericCarrierMock, IntlMockAdapter
from app.adapters.sf_filter_mock import SFFilterMockAdapter
from app.engine.rule_engine import EvalContext, RuleEngine
from app.models.schemas import (
    AddressInput,
    CarrierFilterResult,
    GeocodeResult,
    ParsedAddress,
    ReachabilityRequest,
    ReachabilityResponse,
    ReachabilityStatus,
    Reason,
    Severity,
    StageTrace,
)


def _ms(start: float) -> float:
    return round((time.perf_counter() - start) * 1000, 2)


class ReachabilityPipeline:
    def __init__(self, engine: RuleEngine, fengtu=None):
        self.engine = engine
        # Prefer live Fengtu when FENGTU_APP_KEY is set; else mock.
        if fengtu is not None:
            self.fengtu = fengtu
        else:
            live = FengtuClient.from_env()
            self.fengtu = live if live is not None else FengtuMockAdapter()
        self.fengtu_mode = "live" if getattr(self.fengtu, "name", "") == "fengtu_live" else "mock"
        self.intl = IntlMockAdapter()
        self.sf = SFFilterMockAdapter()
        self.generic_carrier = GenericCarrierMock()

    def run(self, req: ReachabilityRequest) -> ReachabilityResponse:
        request_id = str(uuid.uuid4())
        addr = req.address
        country = (addr.country or "").upper() or None
        raw = addr.raw or self._compose_raw(addr)
        fields = self._fields_from_input(addr)
        ctx = EvalContext(
            country=country,
            raw=raw,
            cleaned_raw=raw,
            fields=fields,
            sample_tag=addr.sample_tag,
        )
        traces: list[StageTrace] = []

        # 1) clean
        t0 = time.perf_counter()
        self.engine.evaluate_stage("clean", ctx)
        if ctx.cleaned_raw:
            fields["cleaned_raw"] = ctx.cleaned_raw
        traces.append(
            StageTrace(
                stage="clean",
                ok=True,
                duration_ms=_ms(t0),
                notes=list(ctx.notes),
                data={"cleaned_raw": ctx.cleaned_raw},
            )
        )
        ctx.notes.clear()

        # Infer country if still missing from raw heuristics (samples)
        if not ctx.country:
            ctx.blocked = True
            ctx.reasons.append(
                Reason(
                    code="ADDR_COUNTRY_MISSING",
                    message="Country is required for routing",
                    path="address.country",
                    severity=Severity.BLOCK,
                    rule_id="PARSE_MISSING_COUNTRY",
                    stage="parse",
                )
            )

        router = self.engine.router_for(ctx.country)
        parsed: Optional[ParsedAddress] = None
        geocode: Optional[GeocodeResult] = None
        carrier: Optional[CarrierFilterResult] = None

        # 2) parse
        t0 = time.perf_counter()
        if ctx.country:
            if router.get("parser") == "fengtu":
                parsed = self.fengtu.parse(ctx.cleaned_raw or raw, fields)
            else:
                parsed = self.intl.parse(ctx.country, ctx.cleaned_raw or raw, fields)
            # sync fields for rule matching
            ctx.fields.update(
                {
                    "province": parsed.province,
                    "admin1": parsed.admin1,
                    "city": parsed.city,
                    "locality": parsed.locality,
                    "admin2": parsed.admin2,
                    "suburb": parsed.suburb,
                    "road": parsed.road,
                    "house_number": parsed.house_number,
                    "postal_code": parsed.postal_code,
                }
            )
            # BR postal invalid flag
            if ctx.country == "BR":
                ctx.postal_code_invalid = bool(
                    getattr(parsed, "__dict__", {}).get("_postal_invalid", False)
                )
                if parsed.postal_code:
                    digits = re.sub(r"\D", "", parsed.postal_code)
                    ctx.postal_code_invalid = len(digits) != 8
                else:
                    ctx.postal_code_invalid = True
            if ctx.country == "ZA":
                pc = parsed.postal_code or ""
                ctx.postal_code_invalid = not bool(re.fullmatch(r"\d{4}", pc))
        self.engine.evaluate_stage("parse", ctx)
        traces.append(
            StageTrace(
                stage="parse",
                ok=not any(r.stage == "parse" and r.severity == Severity.BLOCK for r in ctx.reasons),
                duration_ms=_ms(t0),
                notes=list(ctx.notes),
                data={"parsed": parsed.model_dump() if parsed else None},
            )
        )
        ctx.notes.clear()

        # Early exit if hard-blocked on incompleteness (still run validate lightly)
        # 3) validate
        t0 = time.perf_counter()
        self.engine.evaluate_stage("validate", ctx)
        traces.append(
            StageTrace(
                stage="validate",
                ok=not any(
                    r.stage == "validate" and r.severity == Severity.BLOCK for r in ctx.reasons
                ),
                duration_ms=_ms(t0),
                data={"postal_code_invalid": ctx.postal_code_invalid},
            )
        )

        # Attach Fengtu live API errors from parse (if any)
        if router.get("parser") == "fengtu" and hasattr(self.fengtu, "last_error"):
            err = getattr(self.fengtu, "last_error", None)
            if err and err.get("stage") == "parse":
                ctx.reasons.append(
                    Reason(
                        code=err.get("reason_code") or "FENGTU_HTTP_ERROR",
                        message=err.get("message") or "Fengtu API error",
                        path="stage.parse",
                        severity=Severity.WARN,
                        stage="parse",
                        details={"http_status": err.get("http_status")},
                    )
                )

        # 4) geocode / verify
        t0 = time.perf_counter()
        if parsed and ctx.country:
            if router.get("geocoder") == "fengtu":
                verify = self.fengtu.verify(parsed)
                ctx.verify_ok = bool(verify.get("ok"))
                if verify.get("reason_code"):
                    ctx.reasons.append(
                        Reason(
                            code=verify["reason_code"],
                            message=verify.get("message") or "Fengtu verify error",
                            path="stage.verify",
                            severity=Severity.WARN,
                            stage="verify",
                        )
                    )
                self.engine.evaluate_stage("verify", ctx)
                geocode = self.fengtu.geocode(parsed)
                err = getattr(self.fengtu, "last_error", None)
                if err and err.get("stage") == "geocode":
                    ctx.reasons.append(
                        Reason(
                            code=err.get("reason_code") or "FENGTU_HTTP_ERROR",
                            message=err.get("message") or "Fengtu geocode error",
                            path="stage.geocode",
                            severity=Severity.WARN,
                            stage="geocode",
                            details={"http_status": err.get("http_status")},
                        )
                    )
            else:
                geocode = self.intl.geocode(
                    parsed,
                    sample_tag=ctx.sample_tag,
                    hint_lat=addr.lat,
                    hint_lng=addr.lng,
                )
            ctx.geocode_confidence = geocode.confidence
            ctx.geocode_dispute_km = geocode.dispute_km or 0.0
            self.engine.evaluate_stage("geocode", ctx)
        traces.append(
            StageTrace(
                stage="geocode",
                ok=not any(
                    r.stage in ("geocode", "verify") and r.severity == Severity.BLOCK
                    for r in ctx.reasons
                ),
                duration_ms=_ms(t0),
                data={
                    "geocode": geocode.model_dump() if geocode else None,
                    "verify_ok": ctx.verify_ok,
                },
            )
        )

        # 5) carrier filter
        t0 = time.perf_counter()
        if parsed:
            if router.get("carrier_filter") == "sf_express" or req.carrier == "sf_express":
                # For intl countries still allow generic unless CN
                if ctx.country == "CN":
                    carrier = self.sf.filter_order(
                        parsed, product_code=req.product_code, extra=req.options
                    )
                else:
                    carrier = self.generic_carrier.filter_order(
                        parsed, sample_tag=ctx.sample_tag
                    )
            else:
                carrier = self.generic_carrier.filter_order(
                    parsed, sample_tag=ctx.sample_tag
                )
            ctx.filter_result = carrier.filter_result
            self.engine.evaluate_stage("carrier_filter", ctx)
        traces.append(
            StageTrace(
                stage="carrier_filter",
                ok=not any(
                    r.stage == "carrier_filter" and r.severity == Severity.BLOCK
                    for r in ctx.reasons
                ),
                duration_ms=_ms(t0),
                data={"carrier_filter": carrier.model_dump() if carrier else None},
            )
        )

        # 6) aggregate
        score = self._score(parsed, geocode, carrier, ctx)
        status, reachable = self._status(ctx, score)

        return ReachabilityResponse(
            status=status,
            reachable=reachable,
            deliverability_score=score,
            reasons=ctx.reasons,
            parsed=parsed,
            geocode=geocode,
            carrier_filter=carrier,
            pipeline=traces,
            rules_version=self.engine.version,
            request_id=request_id,
        )

    def _score(
        self,
        parsed: Optional[ParsedAddress],
        geocode: Optional[GeocodeResult],
        carrier: Optional[CarrierFilterResult],
        ctx: EvalContext,
    ) -> float:
        w = self.engine.score_weights or {
            "completeness": 0.3,
            "parse_confidence": 0.15,
            "verify": 0.2,
            "geocode_confidence": 0.2,
            "carrier_in_service": 0.15,
        }
        completeness = 1.0 if parsed and parsed.completeness == "sufficient" else 0.2
        parse_c = parsed.parse_confidence if parsed else 0.0
        verify = 1.0 if ctx.verify_ok else 0.0
        geo = geocode.confidence if geocode else 0.0
        carr = 1.0 if carrier and carrier.filter_result == 2 else 0.0
        score = 100 * (
            w.get("completeness", 0.3) * completeness
            + w.get("parse_confidence", 0.15) * parse_c
            + w.get("verify", 0.2) * verify
            + w.get("geocode_confidence", 0.2) * geo
            + w.get("carrier_in_service", 0.15) * carr
        )
        # Cap when blocked
        if ctx.blocked:
            score = min(score, 49.0)
        return round(score, 2)

    def _status(
        self, ctx: EvalContext, score: float
    ) -> tuple[ReachabilityStatus, bool]:
        min_score = float(self.engine.defaults.get("min_deliverability_score", 70))
        if ctx.blocked:
            return ReachabilityStatus.UNREACHABLE, False
        if ctx.soft_blocked or score < min_score:
            return ReachabilityStatus.NEEDS_REVIEW, False
        return ReachabilityStatus.REACHABLE, True

    @staticmethod
    def _compose_raw(addr: AddressInput) -> str:
        if (addr.country or "").upper() == "CN":
            parts = [
                addr.province,
                addr.city,
                addr.county or addr.district,
                addr.suburb,
                addr.road,
                addr.house_number,
                addr.postal_code,
            ]
            return "".join(p for p in parts if p)
        parts = [
            addr.road,
            addr.house_number,
            addr.suburb,
            addr.city or addr.locality,
            addr.admin1 or addr.province,
            addr.postal_code,
        ]
        return ", ".join(p for p in parts if p)

    @staticmethod
    def _fields_from_input(addr: AddressInput) -> dict[str, Any]:
        return {
            k: v
            for k, v in {
                "province": addr.province,
                "admin1": addr.admin1,
                "city": addr.city,
                "locality": addr.locality,
                "admin2": addr.admin2,
                "suburb": addr.suburb,
                "road": addr.road,
                "house_number": addr.house_number,
                "postal_code": addr.postal_code,
                "county": addr.county,
                "district": addr.district,
            }.items()
            if v is not None
        }
