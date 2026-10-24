#!/usr/bin/env python3
"""Offline smoke: run four global samples + CN without HTTP."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.engine.rule_engine import RuleEngine
from app.models.schemas import ReachabilityRequest
from app.pipeline.runner import ReachabilityPipeline

SAMPLES = json.loads((ROOT / "samples" / "requests.json").read_text(encoding="utf-8"))


def main() -> None:
    engine = RuleEngine(ROOT / "config" / "rules.yaml")
    pipe = ReachabilityPipeline(engine)
    out = {}
    for name, body in SAMPLES.items():
        resp = pipe.run(ReachabilityRequest.model_validate(body))
        out[name] = {
            "status": resp.status.value,
            "reachable": resp.reachable,
            "deliverability_score": resp.deliverability_score,
            "reasons": [
                {"code": r.code, "path": r.path, "rule_id": r.rule_id, "severity": r.severity.value}
                for r in resp.reasons
            ],
            "filter_result": resp.carrier_filter.filter_result if resp.carrier_filter else None,
            "geocode_confidence": resp.geocode.confidence if resp.geocode else None,
            "dispute_km": resp.geocode.dispute_km if resp.geocode else None,
        }
        print(f"=== {name} ===")
        print(json.dumps(out[name], ensure_ascii=False, indent=2))
    (ROOT / "samples" / "smoke_results.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("\nWrote samples/smoke_results.json")


if __name__ == "__main__":
    main()
