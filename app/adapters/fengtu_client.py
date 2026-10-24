"""
Real SF Fengtu (顺丰丰图) SaaS client — official 2.0 SaaS paths.

Uses env FENGTU_APP_KEY only via os.environ — never print/log/write the key value.
Redact any accidental inclusion in error messages.

Verified LIVE endpoints (quota console; Header `ak`):
  - GET  /oplbs/v1/geocode/geo
  - POST /opsearch/v1/place/addressidentify
  - POST /opquery/v1/addressRealCheck
  - POST /opquery/v1/addressResolve

Old broken defaults (403 consumer_name forbidden) — NOT used:
  - /pai/api/addressidentify
  - /all/api/geocode/geo
"""

from __future__ import annotations

import os
import re
from typing import Any, Optional

import httpx

from app.models.schemas import GeocodeResult, ParsedAddress

BASE = "https://gis-apis.sf-express.com"
GEOCODE_URL = f"{BASE}/oplbs/v1/geocode/geo"
ADDRESSIDENTIFY_URL = f"{BASE}/opsearch/v1/place/addressidentify"
ADDRESS_RESOLVE_URL = f"{BASE}/opquery/v1/addressResolve"
ADDRESS_REALCHECK_URL = f"{BASE}/opquery/v1/addressRealCheck"

# Reason codes surfaced to the pipeline
REASON_AUTH = "FENGTU_AUTH_FAIL"
REASON_HTTP = "FENGTU_HTTP_ERROR"
REASON_PARSE = "FENGTU_PARSE_FAIL"
REASON_GEO = "FENGTU_GEOCODE_FAIL"
REASON_VERIFY = "FENGTU_VERIFY_FAIL"

_KEY_RE = re.compile(r"[A-Za-z0-9_\-]{16,}")


def _redact(text: str, key: str) -> str:
    if not text:
        return text
    out = text
    if key:
        out = out.replace(key, "***REDACTED***")
    return _KEY_RE.sub(
        lambda m: "***REDACTED***" if len(m.group(0)) >= 20 else m.group(0), out
    )


class FengtuAPIError(Exception):
    """Mapped Fengtu HTTP / auth / business failure."""

    def __init__(self, reason_code: str, message: str, http_status: Optional[int] = None):
        self.reason_code = reason_code
        self.message = message
        self.http_status = http_status
        super().__init__(message)


class FengtuClient:
    """Live China-oriented parse / verify / geocode via gis-apis.sf-express.com 2.0."""

    name = "fengtu_live"

    def __init__(
        self,
        app_key: Optional[str] = None,
        timeout: float = 10.0,
        syscode: str = "SysTEST",
    ):
        key = app_key if app_key is not None else os.environ.get("FENGTU_APP_KEY", "")
        if not key:
            raise ValueError("FENGTU_APP_KEY is empty; cannot construct live FengtuClient")
        self._app_key = key
        self._timeout = timeout
        self._syscode = syscode or os.environ.get("FENGTU_SYSCODE", "SysTEST")
        self.last_error: Optional[dict[str, Any]] = None
        self.last_identify: Optional[dict[str, Any]] = None
        self.last_resolve: Optional[dict[str, Any]] = None
        self.last_realcheck: Optional[dict[str, Any]] = None
        self.last_geocode_raw: Optional[dict[str, Any]] = None
        self.last_parse_source: Optional[str] = None

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
        if (
            status_code in (401, 403)
            or "113" in safe
            or "未授权" in safe
            or "unauthorized" in safe.lower()
            or "forbidden" in safe.lower()
        ):
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

    def _check_biz_status(
        self, data: dict[str, Any], *, fail_reason: str, label: str
    ) -> None:
        status = data.get("status")
        if status in (0, "0", None):
            return
        msg = str(data.get("message") or data.get("msg") or status)
        safe = _redact(msg, self._app_key)
        if status in (1, "1") or "113" in safe or "未授权" in safe:
            raise FengtuAPIError(REASON_AUTH, f"Fengtu {label} auth/biz fail: {safe}")
        raise FengtuAPIError(fail_reason, f"Fengtu {label} status={status}: {safe}")

    def _post_json(self, url: str, payload: dict[str, Any], label: str) -> dict[str, Any]:
        try:
            with httpx.Client(timeout=self._timeout) as client:
                resp = client.post(
                    url,
                    json=payload,
                    headers={"Content-Type": "application/json", **self._headers_ak()},
                )
        except httpx.HTTPError as e:
            raise FengtuAPIError(
                REASON_HTTP, f"Fengtu {label} network error: {e.__class__.__name__}"
            ) from e

        if resp.status_code >= 400:
            raise self._map_http_error(resp.status_code, resp.text)

        try:
            data = resp.json()
        except ValueError as e:
            raise FengtuAPIError(REASON_HTTP, f"Fengtu {label} returned non-JSON") from e

        if not isinstance(data, dict):
            raise FengtuAPIError(REASON_HTTP, f"Fengtu {label} returned non-object JSON")
        return data

    def _post_addressidentify(self, address_text: str) -> dict[str, Any]:
        # ak header required; ak in body optional per quota console
        payload = {
            "addresstext": address_text,
            "syscode": self._syscode,
        }
        data = self._post_json(ADDRESSIDENTIFY_URL, payload, "addressidentify")
        self._check_biz_status(data, fail_reason=REASON_PARSE, label="addressidentify")
        return data

    def _post_address_resolve(self, address: str) -> dict[str, Any]:
        data = self._post_json(ADDRESS_RESOLVE_URL, {"address": address}, "addressResolve")
        self._check_biz_status(data, fail_reason=REASON_PARSE, label="addressResolve")
        return data

    def _post_address_realcheck(self, address: str) -> dict[str, Any]:
        data = self._post_json(
            ADDRESS_REALCHECK_URL, {"address": address}, "addressRealCheck"
        )
        self._check_biz_status(data, fail_reason=REASON_VERIFY, label="addressRealCheck")
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
            raise FengtuAPIError(
                REASON_HTTP, f"Fengtu geocode network error: {e.__class__.__name__}"
            ) from e

        if resp.status_code >= 400:
            raise self._map_http_error(resp.status_code, resp.text)

        try:
            data = resp.json()
        except ValueError as e:
            raise FengtuAPIError(REASON_HTTP, "Fengtu geocode returned non-JSON") from e

        if not isinstance(data, dict):
            raise FengtuAPIError(REASON_HTTP, "Fengtu geocode returned non-object JSON")

        self._check_biz_status(data, fail_reason=REASON_GEO, label="geocode")
        return data

    @staticmethod
    def _extract_addr_block(payload: dict[str, Any]) -> dict[str, Any]:
        """Normalize result.data / paidata.data from identify or resolve responses."""
        result = payload.get("result") or {}
        if not isinstance(result, dict):
            return {}
        paidata = result.get("paidata") or {}
        if isinstance(paidata, dict):
            nested = paidata.get("data")
            if isinstance(nested, dict) and (
                nested.get("province") or nested.get("city") or nested.get("vilName")
            ):
                return nested
        data = result.get("data")
        if isinstance(data, dict):
            return data
        # Some resolve shapes put fields directly on result
        if result.get("province") or result.get("city") or result.get("vilName"):
            return result
        return {}

    def parse(self, raw: str, fields: dict[str, Any]) -> ParsedAddress:
        """Prefer addressResolve; fall back to addressidentify."""
        self.last_error = None
        self.last_parse_source = None
        block: dict[str, Any] = {}
        source: Optional[str] = None

        # 1) Prefer addressResolve
        try:
            resolve = self._post_address_resolve(raw)
            self.last_resolve = resolve
            block = self._extract_addr_block(resolve)
            if block.get("province") or block.get("city"):
                source = "addressResolve"
        except FengtuAPIError as e:
            self.last_resolve = None
            resolve_err = e
        else:
            resolve_err = None

        # 2) Fall back to addressidentify
        if source is None:
            try:
                identify = self._post_addressidentify(raw)
                self.last_identify = identify
                block = self._extract_addr_block(identify)
                if block.get("province") or block.get("city"):
                    source = "addressidentify"
                elif resolve_err is None and self.last_resolve is not None:
                    # resolve returned empty block; keep identify as source if any fields
                    source = "addressidentify" if block else None
                else:
                    source = "addressidentify" if block else None
            except FengtuAPIError as e:
                self.last_identify = None
                # Both failed
                if resolve_err is not None:
                    chosen = resolve_err
                else:
                    chosen = e
                self.last_error = {
                    "reason_code": chosen.reason_code,
                    "message": chosen.message,
                    "http_status": chosen.http_status,
                    "stage": "parse",
                }
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

        self.last_parse_source = source or "none"

        province = block.get("province") or fields.get("province")
        city = block.get("city") or fields.get("city")
        county = (
            block.get("county")
            or block.get("district")
            or fields.get("county")
        )
        town = block.get("town") or block.get("vilName") or fields.get("suburb")
        detail = (
            block.get("detailaddr")
            or block.get("detailAddr")
            or block.get("address")
            or fields.get("road")
            or raw
        )
        adcode = block.get("adcode") or block.get("citycode") or block.get("countycode")

        conf = 0.85 if (province and city) else 0.45
        if source == "addressResolve" and province and city:
            conf = 0.9

        return ParsedAddress(
            country="CN",
            province=province,
            city=city,
            county=county,
            district=county,
            suburb=town,
            road=detail,
            postal_code=fields.get("postal_code") or (str(adcode) if adcode else None),
            cleaned_raw=raw,
            parse_confidence=conf,
            completeness="sufficient" if province and city else "insufficient",
        )

    def verify(self, parsed: ParsedAddress) -> dict[str, Any]:
        """Use addressRealCheck; addressTrue e.g. '真实' means ok."""
        if self.last_error and self.last_error.get("stage") == "parse":
            return {
                "ok": False,
                "level": "api_error",
                "message": self.last_error.get("message", "fengtu parse failed"),
                "reason_code": self.last_error.get("reason_code"),
            }

        address = parsed.cleaned_raw or " ".join(
            p for p in [parsed.province, parsed.city, parsed.county, parsed.road] if p
        )
        try:
            data = self._post_address_realcheck(address)
            self.last_realcheck = data
        except FengtuAPIError as e:
            self.last_error = {
                "reason_code": e.reason_code,
                "message": e.message,
                "http_status": e.http_status,
                "stage": "verify",
            }
            # Soft fallback if realcheck unavailable but parse looked good
            if parsed.province and parsed.city and parsed.parse_confidence >= 0.7:
                return {
                    "ok": True,
                    "level": "derived_confidence",
                    "message": f"realcheck unavailable ({e.reason_code}); derived from parse",
                    "reason_code": e.reason_code,
                }
            return {
                "ok": False,
                "level": "api_error",
                "message": e.message,
                "reason_code": e.reason_code,
            }

        result = data.get("result") or {}
        if not isinstance(result, dict):
            result = {}
        address_true = result.get("addressTrue") or result.get("address_true")
        true_str = str(address_true).strip() if address_true is not None else ""

        if true_str in ("真实", "true", "True", "1", "Y", "yes"):
            return {
                "ok": True,
                "level": "address_true",
                "message": f"addressTrue={true_str}",
            }
        if true_str in ("虚假", "false", "False", "0", "N", "no"):
            return {
                "ok": False,
                "level": "address_false",
                "message": f"addressTrue={true_str}",
                "reason_code": REASON_VERIFY,
            }

        # Unknown / empty addressTrue — use parse completeness
        if parsed.province and parsed.city and parsed.parse_confidence >= 0.7:
            return {
                "ok": True,
                "level": "derived_confidence",
                "message": f"addressTrue unset ({true_str!r}); derived from parse",
            }
        return {
            "ok": False,
            "level": "incomplete",
            "message": f"addressTrue unset ({true_str!r}) and parse incomplete",
            "reason_code": REASON_VERIFY,
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
                    "src_level_desc": result.get("src_level_desc")
                    or result.get("srcleveldesc"),
                    "geo_level_desc": result.get("geo_level_desc")
                    or result.get("geoleveldesc"),
                    "province": result.get("province"),
                    "city": result.get("city"),
                    "district": result.get("district"),
                }
            ]
            if result
            else [],
        )
