"""
Mock international parse / geocode adapter (Google/Loqate/Melissa stand-in).

Used when country != CN. Coordinates are WGS84. No real vendor credentials.
"""

from __future__ import annotations

import math
import re
from typing import Any, Optional

from app.models.schemas import GeocodeResult, ParsedAddress

BR_UF = {
    "SP": "São Paulo",
    "RJ": "Rio de Janeiro",
    "MG": "Minas Gerais",
}


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


class IntlMockAdapter:
    name = "intl_mock"

    def parse(
        self, country: str, raw: str, fields: dict[str, Any]
    ) -> ParsedAddress:
        country = (country or "").upper()
        cleaned = fields.get("cleaned_raw") or raw
        parsed_fields = dict(fields)

        if country == "ZA":
            # Extract 4-digit postal if glued
            m = re.search(r"(\d{4})\b", cleaned or "")
            pc = parsed_fields.get("postal_code") or (m.group(1) if m else None)
            # Rough locality hints
            locality = parsed_fields.get("locality") or parsed_fields.get("city")
            if not locality and cleaned and "Boksburg" in cleaned:
                locality = "Boksburg North"
            suburb = parsed_fields.get("suburb")
            if not suburb and cleaned and "Anderbolt" in cleaned:
                suburb = "Anderbolt"
            road = parsed_fields.get("road")
            if not road and cleaned and "Dam" in cleaned and "Main" in cleaned:
                road = "Cnr of Dam and Main Road"
            admin1 = parsed_fields.get("admin1") or parsed_fields.get("province")
            if not admin1 and cleaned and "Gauteng" in cleaned:
                admin1 = "Gauteng"
            complete = bool(locality and (pc or road))
            return ParsedAddress(
                country="ZA",
                admin1=admin1,
                province=admin1,
                city=locality,
                locality=locality,
                suburb=suburb,
                road=road,
                postal_code=pc,
                cleaned_raw=cleaned,
                parse_confidence=0.65 if complete else 0.35,
                completeness="sufficient" if complete else "insufficient",
            )

        if country == "BR":
            parts = [p.strip() for p in (cleaned or "").split(",") if p.strip()]
            # Heuristic from sample: ...,TAMBORE,SANTANA DE PARNAIBA,SP,06.543-325
            admin1 = parsed_fields.get("admin1")
            postal = parsed_fields.get("postal_code")
            city = parsed_fields.get("city") or parsed_fields.get("locality")
            suburb = parsed_fields.get("suburb")
            house = parsed_fields.get("house_number")
            road = parsed_fields.get("road")
            if parts:
                # try last as CEP
                last = parts[-1].replace(".", "")
                if re.match(r"\d{5}-?\d{3}", last):
                    postal = postal or last
                    if len(parts) >= 2 and len(parts[-2]) == 2:
                        admin1 = admin1 or parts[-2].upper()
                    if len(parts) >= 3:
                        city = city or parts[-3]
                    if len(parts) >= 4:
                        suburb = suburb or parts[-4]
                    # house number often numeric mid-list
                    for p in parts:
                        if p.isdigit():
                            house = house or p
                            break
                    for p in parts:
                        if "ALAMEDA" in p.upper() or "RUA" in p.upper() or "AV" in p.upper():
                            road = road or p
                            break
            # Normalize CEP
            postal_norm = None
            postal_invalid = True
            if postal:
                digits = re.sub(r"\D", "", postal)
                if len(digits) == 8:
                    postal_norm = f"{digits[:5]}-{digits[5:]}"
                    postal_invalid = False
            if admin1 and admin1.upper() in BR_UF:
                parsed_fields["admin1_expanded"] = BR_UF[admin1.upper()]
            complete = bool(city and postal_norm and road)
            pa = ParsedAddress(
                country="BR",
                admin1=(admin1 or "").upper() or None,
                province=BR_UF.get((admin1 or "").upper(), admin1),
                city=city,
                locality=city,
                suburb=suburb,
                road=road,
                house_number=house,
                postal_code=postal_norm,
                cleaned_raw=cleaned,
                parse_confidence=0.8 if complete else 0.4,
                completeness="sufficient" if complete else "insufficient",
            )
            # stash invalid flag on object via dict later
            pa.__dict__["_postal_invalid"] = postal_invalid and bool(postal or True)
            if postal_norm:
                pa.__dict__["_postal_invalid"] = False
            elif not postal:
                pa.__dict__["_postal_invalid"] = True
            return pa

        if country == "ID":
            road = parsed_fields.get("road") or cleaned
            if road and road.upper().startswith("JL"):
                road = re.sub(r"(?i)^jl\.?\s*", "Jalan ", road.strip())
            city = parsed_fields.get("city") or parsed_fields.get("locality")
            complete = bool(city or parsed_fields.get("postal_code"))
            return ParsedAddress(
                country="ID",
                road=road,
                city=city,
                locality=city,
                postal_code=parsed_fields.get("postal_code"),
                cleaned_raw=cleaned,
                parse_confidence=0.25 if not complete else 0.7,
                completeness="sufficient" if complete else "insufficient",
            )

        if country == "CO":
            road = parsed_fields.get("road") or cleaned
            city = parsed_fields.get("city") or parsed_fields.get("locality")
            # Transversal pattern
            m = re.search(
                r"(?i)(Transversal|Calle|Carrera|Diagonal)\s+(\d+\w*)\s*No\.?\s*([\w\-]+)",
                cleaned or "",
            )
            house = parsed_fields.get("house_number")
            road_type = None
            if m:
                road_type, num, house = m.group(1), m.group(2), house or m.group(3)
                road = f"{road_type} {num}"
            complete = bool(city and road)
            return ParsedAddress(
                country="CO",
                road=road,
                house_number=house,
                city=city,
                locality=city,
                postal_code=parsed_fields.get("postal_code"),
                cleaned_raw=cleaned,
                parse_confidence=0.45 if not city else 0.75,
                completeness="sufficient" if complete else "insufficient",
            )

        # Generic fallback
        return ParsedAddress(
            country=country or None,
            road=parsed_fields.get("road") or cleaned,
            city=parsed_fields.get("city"),
            locality=parsed_fields.get("locality"),
            admin1=parsed_fields.get("admin1"),
            postal_code=parsed_fields.get("postal_code"),
            cleaned_raw=cleaned,
            parse_confidence=0.3,
            completeness="unknown",
        )

    def geocode(
        self,
        parsed: ParsedAddress,
        *,
        sample_tag: Optional[str] = None,
        hint_lat: Optional[float] = None,
        hint_lng: Optional[float] = None,
    ) -> GeocodeResult:
        country = (parsed.country or "").upper()

        # Colombia bad geocode fixture: two candidates far apart
        if country == "CO" and (
            sample_tag == "co_bad_geocode"
            or (parsed.road and "Transversal 32" in (parsed.road or ""))
        ):
            # Business-supplied wrong vs claimed-correct (lng, lat order in source notes)
            wrong = (-74.1786585607365, 4.28400375)  # lng, lat
            right = (-74.15326735048153, 4.56742069886296)
            dispute = _haversine_km(wrong[1], wrong[0], right[1], right[0])
            # Return the BAD candidate as primary (simulating bad provider pick)
            return GeocodeResult(
                lat=wrong[1],
                lng=wrong[0],
                confidence=0.32,
                provider=self.name,
                coordinate_system="WGS84",
                dispute_km=round(dispute, 2),
                candidates=[
                    {
                        "label": "bad_candidate",
                        "lat": wrong[1],
                        "lng": wrong[0],
                        "confidence": 0.32,
                    },
                    {
                        "label": "claimed_correct",
                        "lat": right[1],
                        "lng": right[0],
                        "confidence": 0.7,
                        "note": "business-supplied; not independently verified",
                    },
                ],
            )

        if country == "ZA" and parsed.locality:
            return GeocodeResult(
                lat=-26.177,
                lng=28.239,
                confidence=0.72,
                provider=self.name,
                coordinate_system="WGS84",
            )

        if country == "BR" and parsed.postal_code:
            return GeocodeResult(
                lat=-23.451,
                lng=-46.853,
                confidence=0.88,
                provider=self.name,
                coordinate_system="WGS84",
            )

        if country == "ID":
            # Incomplete → low confidence multi-match
            return GeocodeResult(
                lat=None,
                lng=None,
                confidence=0.15,
                provider=self.name,
                coordinate_system="WGS84",
                candidates=[
                    {"label": "ambiguous_road_only", "note": "Gandaria I exists in multiple cities"}
                ],
            )

        if hint_lat is not None and hint_lng is not None:
            return GeocodeResult(
                lat=hint_lat,
                lng=hint_lng,
                confidence=0.5,
                provider=self.name,
                coordinate_system="WGS84",
            )

        return GeocodeResult(
            lat=None,
            lng=None,
            confidence=0.2,
            provider=self.name,
            coordinate_system="WGS84",
        )


class GenericCarrierMock:
    name = "generic_mock"

    def filter_order(self, parsed: ParsedAddress, **kwargs) -> "CarrierFilterResult":
        from app.models.schemas import CarrierFilterResult

        if parsed.completeness == "insufficient":
            return CarrierFilterResult(
                filter_result=4, remark="incomplete", carrier=self.name
            )
        if (parsed.country or "").upper() == "CO" and kwargs.get("sample_tag") == "co_bad_geocode":
            return CarrierFilterResult(
                filter_result=3, remark="2", carrier=self.name
            )
        return CarrierFilterResult(
            filter_result=2,
            origin_code="GEN",
            dest_code="GEN",
            carrier=self.name,
        )
