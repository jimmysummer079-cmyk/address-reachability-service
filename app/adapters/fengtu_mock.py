"""
Mock Fengtu (顺丰丰图) address adapter.

Interface only — does NOT call lbs.sfmap.com.cn.
Product references (public docs, no credentials):
  - https://lbs.sfmap.com.cn/product/ft-address-services
  - https://lbs.sfmap.com.cn/sfmapsdk-doc/ftmap_2d_jsapi/Geocoder.html
  - https://lbs.sfmap.com.cn/sfmapsdk-doc/ftmap_webservice_api/03-reverse-geocoding.html
"""

from __future__ import annotations

from typing import Any

from app.models.schemas import GeocodeResult, ParsedAddress


class FengtuMockAdapter:
    """China-oriented parse / verify / geocode stub."""

    name = "fengtu_mock"

    def parse(self, raw: str, fields: dict[str, Any]) -> ParsedAddress:
        # Very small heuristic for demo CN strings; production = Fengtu API
        province = fields.get("province")
        city = fields.get("city")
        county = fields.get("county") or fields.get("district")
        road = fields.get("road") or raw
        conf = 0.9 if province and city else 0.4
        return ParsedAddress(
            country="CN",
            province=province,
            city=city,
            county=county,
            road=road,
            postal_code=fields.get("postal_code"),
            cleaned_raw=raw,
            parse_confidence=conf,
            completeness="sufficient" if province and city else "insufficient",
        )

    def verify(self, parsed: ParsedAddress) -> dict[str, Any]:
        """Simulated address verify / level check."""
        if not parsed.province or not parsed.city:
            return {"ok": False, "level": "incomplete", "message": "below level threshold"}
        if parsed.road and "虚假" in (parsed.road or ""):
            return {"ok": False, "level": "fake", "message": "verify rejected"}
        return {"ok": True, "level": "door", "message": "verify passed (mock)"}

    def geocode(self, parsed: ParsedAddress) -> GeocodeResult:
        # Mock Shenzhen HQ pin in GCJ-02 narrative space
        if parsed.city and "深圳" in parsed.city:
            return GeocodeResult(
                lat=22.5405,
                lng=113.9345,
                confidence=0.92,
                provider=self.name,
                coordinate_system="GCJ-02",
            )
        return GeocodeResult(
            lat=None,
            lng=None,
            confidence=0.2,
            provider=self.name,
            coordinate_system="GCJ-02",
        )
