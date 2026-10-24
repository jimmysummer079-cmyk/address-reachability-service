"""
Real SF Fengtu (顺丰丰图) SaaS client.

Uses env FENGTU_APP_KEY only via os.environ — never print/log/write the key value.
Redact any accidental inclusion in error messages.

Endpoints (third-party writeups + SaaS host; see FENGTU_LIVE.md for live status):
  - POST https://gis-apis.sf-express.com/pai/api/addressidentify
  - GET  https://gis-apis.sf-express.com/all/api/geocode/geo  (Header: ak)
"""

from __future__ import annotations

import os
import re
from typing import Any, Optional

import httpx

from app.models.schemas import GeocodeResult, ParsedAddress

BASE = "https://gis-apis.sf-express.com"
ADDRESSIDENTIFY_URL = f"{BASE}/pai/api/addressidentify"
GEOCODE_URL = f"{BASE}/all/api/geocode/geo"

# Reason codes surfaced to the pipeline
REASON_AUTH = "FENGTU_AUTH_FAIL"
REASON_HTTP = "FENGTU_HTTP_ERROR"
REASON_PARSE = "FENGTU_PARSE_FAIL"
REASON_GEO = "FENGTU_GEOCODE_FAIL"

_KEY_RE = re.compile(r"[A-Za-z0-9_\-]{16,}")


def _redact(text: str, key: str) -> str:
    if not text:
        return text
    out = text
    if key:
        out = out.replace(key, "***REDACTED***")
    # Avoid leaking long token-like substrings in error bodies
    return _KEY_RE.sub(lambda m: "***REDACTED***" if len(m.group(0)) >= 20 else m.group(0), out)


class FengtuAPIError(Exception):
    """Mapped Fengtu HTTP / auth / business failure."""

    def __init__(self, reason_code: str, message: str, http_status: Optional[int] = None):
        self.reason_code = reason_code
        self.message = message
        self.http_status = http_status
        super().__init__(message)


class FengtuClient:
    """Live China-oriented parse / verify / geocode via gis-apis.sf-express.com."""

    name = "fengtu_live"

    def __init__(
        self,
        app_key: Optional[str] = None,
        timeout: float = 10.0,
        syscode: Optional[str] = None,
    ):
        key = app_key if app_key is not None else os.environ.get("FENGTU_APP_KEY", "")
        if not key:
            raise ValueError("FENGTU_APP_KEY is empty; cannot construct live FengtuClient")
        self._app_key = key
        self._timeout = timeout
        # Default arg must stay None so FENGTU_SYSCODE is not shadowed by "SysTEST".
        self._syscode = syscode or os.environ.get("FENGTU_SYSCODE", "SysTEST")
        # Last call diagnostics (no secrets)
        self.last_error: Optional[dict[str, Any]] = None
        self.last_identify: Optional[dict[str, Any]] = None
        self.last_geocode_raw: Optional[dict[str, Any]] = None

    @staticmethod
    def from_env() -> Optional["FengtuClient"]:
        key = os.environ.get("FENGTU_APP_KEY", "").strip()
        if not key:
            return None
        return FengtuClient(app_key=key)

    def _headers_ak(self) -> dict[str, str]:
        return {"ak": self._app_key}

    def _map_http_error(self, status_code: int, body_text: str) -> FengtuAPIError:
        safe = _redact(body_text[:500], self._app_key)
        if status_code in (401, 403) or "113" in safe or "未授权" in safe or "unauthorized" in safe.lower():
            return FengtuAPIError(
                REASON_AUTH,
                f"Fengtu auth failed (HTTP {status_code})",
                http_status=status_code,
            )
        return FengtuAPIError(
            REASON_HTTP,
            f"Fengtu HTTP error {status_code}: {safe}",
            http_status=status_code,
        )

    def _post_identify(self, address_text: str) -> dict[str, Any]:
        payload = {
            "ak": self._app_key,
            "addresstext": address_text,
            "syscode": self._syscode,
            "showcode": "1",
        }
        try:
            with httpx.Client(timeout=self._timeout) as client:
                resp = client.post(
                    ADDRESSIDENTIFY_URL,
                    json=payload,
                    headers={"Content-Type": "application/json", **self._headers_ak()},
                )
        except httpx.HTTPError as e:
            raise FengtuAPIError(REASON_HTTP, f"Fengtu identify network error: {e.__class__.__name__}") from e

        if resp.status_code >= 400:
            raise self._map_http_error(resp.status_code, resp.text)

        try:
            data = resp.json()
        except ValueError as e:
            raise FengtuAPIError(REASON_HTTP, "Fengtu identify returned non-JSON") from e

        # Business-level auth / fail
        status = data.get("status")
        if status not in (0, "0", None):
            msg = str(data.get("message") or data.get("msg") or status)
            safe = _redact(msg, self._app_key)
            if status in (1, "1") or "113" in safe or "未授权" in safe:
                raise FengtuAPIError(REASON_AUTH, f"Fengtu identify auth/biz fail: {safe}")
            raise FengtuAPIError(REASON_PARSE, f"Fengtu identify status={status}: {safe}")

        return data

    def _get_geocode(self, address: str, city: Optional[str] = None) -> dict[str, Any]:
        params: dict[str, Any] = {"address": address, "cc": 1}
        if city:
            params["city"] = city
        try:
            with httpx.Client(timeout=self._timeout) as client:
                resp = client.get(
                    GEOCODE_URL,
                    params=params,
                    headers=self._headers_ak(),
                )
        except httpx.HTTPError as e:
            raise FengtuAPIError(REASON_HTTP, f"Fengtu geocode network error: {e.__class__.__name__}") from e

        if resp.status_code >= 400:
            raise self._map_http_error(resp.status_code, resp.text)

        try:
            data = resp.json()
        except ValueError as e:
            raise FengtuAPIError(REASON_HTTP, "Fengtu geocode returned non-JSON") from e

        status = data.get("status")
        if status not in (0, "0"):
            msg = str(data.get("message") or data.get("msg") or status)
            safe = _redact(msg, self._app_key)
            if status in (1, "1") or "113" in safe or "未授权" in safe:
                raise FengtuAPIError(REASON_AUTH, f"Fengtu geocode auth/biz fail: {safe}")
            raise FengtuAPIError(REASON_GEO, f"Fengtu geocode status={status}: {safe}")

        return data

    @staticmethod
    def _extract_addr_block(identify: dict[str, Any]) -> dict[str, Any]:
        """Handle both paidata.data and result.data nestings from third-party samples."""
        result = identify.get("result") or {}
        if not isinstance(result, dict):
            return {}
        paidata = result.get("paidata") or {}
        if isinstance(paidata, dict):
            nested = paidata.get("data")
            if isinstance(nested, dict) and (nested.get("province") or nested.get("city")):
                return nested
        data = result.get("data")
        if isinstance(data, dict):
            return data
        return {}

    @staticmethod
    def _dispatch_mark(identify: dict[str, Any]) -> Optional[str]:
        result = identify.get("result") or {}
        if not isinstance(result, dict):
            return None
        paidata = result.get("paidata") or {}
        for src in (result, paidata if isinstance(paidata, dict) else {}):
            if isinstance(src, dict) and "dispatchMark" in src:
                return str(src.get("dispatchMark"))
        return None

    def parse(self, raw: str, fields: dict[str, Any]) -> ParsedAddress:
        self.last_error = None
        try:
            identify = self._post_identify(raw)
            self.last_identify = identify
        except FengtuAPIError as e:
            self.last_error = {
                "reason_code": e.reason_code,
                "message": e.message,
                "http_status": e.http_status,
                "stage": "parse",
            }
            # Fall back to input fields so pipeline can still score / reason
            province = fields.get("province")
            city = fields.get("city")
            county = fields.get("county") or fields.get("district")
            return ParsedAddress(
                country="CN",
                province=province,
                city=city,
                county=county,
                road=fields.get("road") or raw,
                postal_code=fields.get("postal_code"),
                cleaned_raw=raw,
                parse_confidence=0.1,
                completeness="insufficient",
            )

        block = self._extract_addr_block(identify)
        province = block.get("province") or fields.get("province")
        city = block.get("city") or fields.get("city")
        county = block.get("county") or block.get("district") or fields.get("county")
        town = block.get("town") or fields.get("suburb")
        detail = block.get("detailaddr") or block.get("address") or fields.get("road") or raw
        adcode = block.get("adcode")

        # Confidence: prefer result-level mark / code
        result = identify.get("result") or {}
        code_ok = str(result.get("code", "0")) in ("0", "")
        conf = 0.85 if (province and city and code_ok) else 0.45
        if self._dispatch_mark(identify) == "1":
            conf = max(conf, 0.9)

        return ParsedAddress(
            country="CN",
            province=province,
            city=city,
            county=county,
            district=county,
            suburb=town,
            road=detail,
            postal_code=fields.get("postal_code") or adcode,
            cleaned_raw=raw,
            parse_confidence=conf,
            completeness="sufficient" if province and city else "insufficient",
        )

    def verify(self, parsed: ParsedAddress) -> dict[str, Any]:
        """
        No dedicated SaaS authenticity endpoint confirmed for this key path.
        Derive from last identify dispatchMark / parse confidence / geocode confidence.
        """
        self.last_error = self.last_error  # preserve parse errors
        if self.last_error and self.last_error.get("stage") == "parse":
            return {
                "ok": False,
                "level": "api_error",
                "message": self.last_error.get("message", "fengtu parse failed"),
                "reason_code": self.last_error.get("reason_code"),
            }

        mark = None
        if self.last_identify:
            mark = self._dispatch_mark(self.last_identify)

        if mark == "1":
            return {"ok": True, "level": "dispatchable", "message": "dispatchMark=1 (derived)"}
        if mark == "0":
            return {"ok": False, "level": "not_dispatchable", "message": "dispatchMark=0 (derived)"}

        if not parsed.province or not parsed.city:
            return {"ok": False, "level": "incomplete", "message": "below level threshold"}
        if parsed.parse_confidence >= 0.7:
            return {
                "ok": True,
                "level": "derived_confidence",
                "message": "verify derived from parse confidence (no authenticity endpoint verified)",
            }
        return {
            "ok": False,
            "level": "low_confidence",
            "message": "verify derived fail: low parse confidence",
        }

    def geocode(self, parsed: ParsedAddress) -> GeocodeResult:
        address = parsed.cleaned_raw or " ".join(
            p for p in [parsed.province, parsed.city, parsed.county, parsed.road] if p
        )
        try:
            data = self._get_geocode(address, city=parsed.city)
            self.last_geocode_raw = data
        except FengtuAPIError as e:
            self.last_error = {
                "reason_code": e.reason_code,
                "message": e.message,
                "http_status": e.http_status,
                "stage": "geocode",
            }
            return GeocodeResult(
                lat=None,
                lng=None,
                confidence=0.0,
                provider=self.name,
                coordinate_system="GCJ-02",
            )

        result = data.get("result") or {}
        if not isinstance(result, dict):
            result = {}

        def _f(v: Any) -> Optional[float]:
            if v is None or v == "":
                return None
            try:
                return float(v)
            except (TypeError, ValueError):
                return None

        lng = _f(result.get("xcoord") or result.get("lng") or result.get("lon"))
        lat = _f(result.get("ycoord") or result.get("lat"))
        raw_conf = result.get("confidence")
        conf = 0.0
        if raw_conf is not None:
            try:
                c = float(raw_conf)
                conf = c / 100.0 if c > 1.0 else c
            except (TypeError, ValueError):
                conf = 0.5 if lat is not None else 0.0
        elif lat is not None and lng is not None:
            conf = 0.75

        return GeocodeResult(
            lat=lat,
            lng=lng,
            confidence=conf,
            provider=self.name,
            coordinate_system="GCJ-02",
            candidates=[
                {
                    "adcode": result.get("adcode"),
                    "standardization": result.get("standardization"),
                    "srcleveldesc": result.get("srcleveldesc"),
                }
            ]
            if result
            else [],
        )
