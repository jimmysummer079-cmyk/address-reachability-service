"""
Mock Fengtu (顺丰丰图) address adapter.

Interface only — does NOT call lbs.sfmap.com.cn.
Product references (public docs, no credentials):
  - https://lbs.sfmap.com.cn/product/ft-address-services
  - https://lbs.sfmap.com.cn/sfmapsdk-doc/ftmap_2d_jsapi/Geocoder.html
  - https://lbs.sfmap.com.cn/sfmapsdk-doc/ftmap_webservice_api/03-reverse-geocoding.html
"""

from __future__ import annotations

import re
from typing import Any, Optional

from app.models.schemas import GeocodeResult, ParsedAddress

# Stand-in for Fengtu addressResolve admin names. Used only when the raw
# string has a city but no province. Not a full gazetteer.
_CITY_PROVINCE = {
    "北京市": "北京市",
    "上海市": "上海市",
    "天津市": "天津市",
    "重庆市": "重庆市",
    "深圳市": "广东省",
    "广州市": "广东省",
    "杭州市": "浙江省",
    "南京市": "江苏省",
    "苏州市": "江苏省",
    "成都市": "四川省",
    "武汉市": "湖北省",
    "西安市": "陕西省",
}

# GCJ-02 pins so a new raw address geocodes from the parsed city, not the previous form.
_CITY_PINS = {
    "深圳": (22.5405, 113.9345, 0.92),
    "广州": (23.1291, 113.2644, 0.9),
    "北京": (39.9042, 116.4074, 0.9),
    "上海": (31.2304, 121.4737, 0.9),
    "杭州": (30.2741, 120.1551, 0.88),
    "南京": (32.0603, 118.7969, 0.88),
    "成都": (30.5728, 104.0668, 0.88),
    "武汉": (30.5928, 114.3055, 0.88),
    "西安": (34.3416, 108.9398, 0.88),
    "苏州": (31.2989, 120.5853, 0.88),
}

_MUNICIPALITIES = ("北京市", "上海市", "天津市", "重庆市")


def segment_cn_address(raw: str) -> dict[str, Optional[str]]:
    """Split a Chinese address the way addressResolve would: province, city, district, road.

    Request structured fields are not an input. Callers apply those only when this
    returns no administrative tokens.
    """
    text = re.sub(r"[\s,，;；]+", "", raw or "")
    out: dict[str, Optional[str]] = {
        "province": None,
        "city": None,
        "county": None,
        "district": None,
        "suburb": None,
        "road": None,
        "house_number": None,
        "postal_code": None,
    }
    if not text:
        return out

    postal = re.search(r"(?<!\d)(\d{6})(?!\d)", text)
    if postal:
        out["postal_code"] = postal.group(1)
        text = text.replace(postal.group(1), "", 1)

    for name in _MUNICIPALITIES:
        if text.startswith(name):
            out["province"] = name
            out["city"] = name
            text = text[len(name) :]
            break
    else:
        province = re.match(r"^(.+?(?:特别行政区|自治区|省))", text)
        if province:
            out["province"] = province.group(1)
            text = text[province.end() :]
        city = re.match(r"^(.+?(?:自治州|地区|盟|市))", text)
        if city:
            out["city"] = city.group(1)
            text = text[city.end() :]

    county = re.match(r"^(.+?(?:自治县|自治旗|林区|特区|区|县|旗|市))", text)
    if county:
        out["county"] = county.group(1)
        out["district"] = county.group(1)
        text = text[county.end() :]

    suburb = re.match(r"^(.+?(?:街道|镇|乡|苏木))", text)
    if suburb:
        out["suburb"] = suburb.group(1)
        text = text[suburb.end() :]

    road = re.match(r"^(.+?(?:大道|大街|路|街|巷|胡同))(\d+号)?", text)
    if road:
        out["road"] = road.group(1)
        out["house_number"] = road.group(2)
    else:
        house = re.match(r"^(\d+号)", text)
        if house:
            out["house_number"] = house.group(1)

    if out["city"] and not out["province"]:
        out["province"] = _CITY_PROVINCE.get(out["city"])
    return out


class FengtuMockAdapter:
    """China-oriented parse / verify / geocode stub. Mirrors Fengtu field roles, no network."""

    name = "fengtu_mock"

    def parse(self, raw: str, fields: dict[str, Any]) -> ParsedAddress:
        """Parse `raw` first. Structured `fields` apply only when raw has no admin tokens."""
        seg = segment_cn_address(raw)
        from_raw = any(seg.get(key) for key in ("province", "city", "county", "road"))
        if not from_raw:
            county = fields.get("county") or fields.get("district")
            seg = {
                "province": fields.get("province"),
                "city": fields.get("city"),
                "county": county,
                "district": fields.get("district") or county,
                "suburb": fields.get("suburb"),
                "road": fields.get("road"),
                "house_number": fields.get("house_number"),
                "postal_code": fields.get("postal_code"),
            }
        conf = 0.9 if seg.get("province") and seg.get("city") else 0.4
        return ParsedAddress(
            country="CN",
            province=seg.get("province"),
            city=seg.get("city"),
            county=seg.get("county"),
            district=seg.get("district") or seg.get("county"),
            suburb=seg.get("suburb"),
            road=seg.get("road"),
            house_number=seg.get("house_number"),
            postal_code=seg.get("postal_code"),
            cleaned_raw=raw,
            parse_confidence=conf,
            completeness="sufficient" if seg.get("province") and seg.get("city") else "insufficient",
        )

    def verify(self, parsed: ParsedAddress) -> dict[str, Any]:
        """Simulated address verify / level check."""
        if not parsed.province or not parsed.city:
            return {"ok": False, "level": "incomplete", "message": "below level threshold"}
        if parsed.road and "虚假" in (parsed.road or ""):
            return {"ok": False, "level": "fake", "message": "verify rejected"}
        return {"ok": True, "level": "door", "message": "verify passed (mock)"}

    def geocode(self, parsed: ParsedAddress) -> GeocodeResult:
        city = parsed.city or ""
        for name, (lat, lng, confidence) in _CITY_PINS.items():
            if name in city:
                return GeocodeResult(
                    lat=lat,
                    lng=lng,
                    confidence=confidence,
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
