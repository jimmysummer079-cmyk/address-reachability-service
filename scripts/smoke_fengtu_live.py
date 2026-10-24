#!/usr/bin/env python3
"""Smoke-test Fengtu live endpoints. Never prints FENGTU_APP_KEY."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

ADDR = "广东省深圳市南山区软件产业基地"


def _shape(obj, depth=0, max_depth=3):
    if depth >= max_depth:
        return type(obj).__name__
    if isinstance(obj, dict):
        return {k: _shape(v, depth + 1, max_depth) for k, v in obj.items()}
    if isinstance(obj, list):
        if not obj:
            return []
        return [_shape(obj[0], depth + 1, max_depth), f"...len={len(obj)}"]
    return type(obj).__name__


def _safe_detail(exc: BaseException, key: str) -> str:
    text = str(exc)[:200]
    if key:
        text = text.replace(key, "***REDACTED***")
    return text


def main() -> int:
    key_set = bool(os.environ.get("FENGTU_APP_KEY", "").strip())
    report: dict = {
        "key_present": key_set,
        "address_len": len(ADDR),
        "addressidentify": {},
        "geocode": {},
        "client_parse": {},
        "client_geocode": {},
    }
    if not key_set:
        report["error"] = "FENGTU_APP_KEY not set"
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 1

    import httpx
    from app.adapters.fengtu_client import (
        ADDRESSIDENTIFY_URL,
        FengtuClient,
        FengtuAPIError,
        GEOCODE_URL,
    )

    key = os.environ["FENGTU_APP_KEY"]

    # 1) raw addressidentify
    try:
        with httpx.Client(timeout=15.0) as client:
            r = client.post(
                ADDRESSIDENTIFY_URL,
                json={"ak": key, "addresstext": ADDR, "syscode": "SysTEST", "showcode": "1"},
                headers={"Content-Type": "application/json", "ak": key},
            )
        body = None
        try:
            body = r.json()
        except Exception:
            body = None
        report["addressidentify"] = {
            "http_status": r.status_code,
            "ok": r.status_code < 400,
            "json_keys": list(body.keys()) if isinstance(body, dict) else None,
            "shape": _shape(body) if body is not None else None,
            "biz_status": body.get("status") if isinstance(body, dict) else None,
        }
    except Exception as e:
        report["addressidentify"] = {"error": e.__class__.__name__, "detail": _safe_detail(e, key)}

    # 2) raw geocode
    try:
        with httpx.Client(timeout=15.0) as client:
            r = client.get(
                GEOCODE_URL,
                params={"address": ADDR, "cc": 1},
                headers={"ak": key},
            )
        body = None
        try:
            body = r.json()
        except Exception:
            body = None
        report["geocode"] = {
            "http_status": r.status_code,
            "ok": r.status_code < 400,
            "json_keys": list(body.keys()) if isinstance(body, dict) else None,
            "shape": _shape(body) if body is not None else None,
            "biz_status": body.get("status") if isinstance(body, dict) else None,
        }
    except Exception as e:
        report["geocode"] = {"error": e.__class__.__name__, "detail": _safe_detail(e, key)}

    # 3) client methods
    client = FengtuClient()
    parsed = client.parse(ADDR, {})
    report["client_parse"] = {
        "provider": client.name,
        "completeness": parsed.completeness,
        "parse_confidence": parsed.parse_confidence,
        "has_province": bool(parsed.province),
        "has_city": bool(parsed.city),
        "last_error": client.last_error,
    }
    verify = client.verify(parsed)
    report["client_verify"] = {
        "ok": verify.get("ok"),
        "level": verify.get("level"),
        "reason_code": verify.get("reason_code"),
    }
    geo = client.geocode(parsed)
    report["client_geocode"] = {
        "has_lat": geo.lat is not None,
        "has_lng": geo.lng is not None,
        "confidence": geo.confidence,
        "provider": geo.provider,
        "last_error": client.last_error,
    }

    # pipeline health mode
    from app.engine.rule_engine import RuleEngine
    from app.pipeline.runner import ReachabilityPipeline
    from app.models.schemas import AddressInput, ReachabilityRequest

    engine = RuleEngine(ROOT / "config" / "rules.yaml")
    pipe = ReachabilityPipeline(engine)
    report["pipeline_fengtu_mode"] = pipe.fengtu_mode
    resp = pipe.run(
        ReachabilityRequest(address=AddressInput(country="CN", raw=ADDR))
    )
    report["pipeline"] = {
        "status": resp.status.value if hasattr(resp.status, "value") else str(resp.status),
        "reachable": resp.reachable,
        "score": resp.deliverability_score,
        "reason_codes": [r.code for r in resp.reasons],
        "geocode_provider": resp.geocode.provider if resp.geocode else None,
        "parsed_completeness": resp.parsed.completeness if resp.parsed else None,
    }

    print(json.dumps(report, ensure_ascii=False, indent=2))

    # Append summary to FENGTU_LIVE.md
    live_md = ROOT / "FENGTU_LIVE.md"
    lines = [
        "",
        "## Integration-time smoke (Asia/Shanghai)",
        "",
        f"- key_present: `{report['key_present']}`",
        f"- addressidentify HTTP: `{report['addressidentify'].get('http_status')}` biz_status=`{report['addressidentify'].get('biz_status')}` keys=`{report['addressidentify'].get('json_keys')}`",
        f"- geocode HTTP: `{report['geocode'].get('http_status')}` biz_status=`{report['geocode'].get('biz_status')}` keys=`{report['geocode'].get('json_keys')}`",
        f"- pipeline mode: `{report['pipeline_fengtu_mode']}` status=`{report['pipeline']['status']}` reasons=`{report['pipeline']['reason_codes']}`",
        "",
    ]
    # Classify verified
    ai_ok = report["addressidentify"].get("http_status") == 200 and report["addressidentify"].get("biz_status") in (0, "0")
    geo_ok = report["geocode"].get("http_status") == 200 and report["geocode"].get("biz_status") in (0, "0")
    lines.append(f"- addressidentify live verified: **{'yes' if ai_ok else 'no'}**")
    lines.append(f"- geocode live verified: **{'yes' if geo_ok else 'no'}**")
    lines.append("")
    with live_md.open("a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    out = ROOT / "samples" / "fengtu_live_smoke.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
