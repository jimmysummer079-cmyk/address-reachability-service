"""
Mock SF Express order-filter (筛单) adapter.

Real service (credentials NOT used here):
  - open.sf-express.com — EXP_RECE_FILTER_ORDER_BSP
  - filterResult: 1人工确认 2可收派 3不可收派 4地址无法确认
  - remark when filterResult=3: 1收方超范围 2派方超范围 3其它

Docs / portals:
  - https://open.sf-express.com/
  - https://qiao.sf-express.com/ (丰桥对接规范 PDF)
"""

from __future__ import annotations

from typing import Any, Optional

from app.models.schemas import CarrierFilterResult, ParsedAddress


class SFFilterMockAdapter:
    name = "sf_express_mock"

    def filter_order(
        self,
        parsed: ParsedAddress,
        *,
        product_code: Optional[str] = None,
        extra: Optional[dict[str, Any]] = None,
    ) -> CarrierFilterResult:
        extra = extra or {}
        # Demo: incomplete / missing locality → 4 地址无法确认
        if parsed.completeness == "insufficient":
            return CarrierFilterResult(
                filter_result=4,
                remark="address unconfirmed (mock)",
                carrier=self.name,
            )
        # Demo tag / road hint for out of service
        if extra.get("force_oos") or (parsed.road and "禁区" in parsed.road):
            return CarrierFilterResult(
                filter_result=3,
                remark="2",  # 派方超范围
                dest_code=None,
                carrier=self.name,
            )
        if parsed.country and parsed.country.upper() != "CN":
            # SF domestic filter not authoritative for intl — still return a mock
            return CarrierFilterResult(
                filter_result=2,
                origin_code="MOCK",
                dest_code="INTL",
                carrier=self.name,
            )
        return CarrierFilterResult(
            filter_result=2,
            origin_code="755",
            dest_code="755",
            carrier=self.name,
        )
