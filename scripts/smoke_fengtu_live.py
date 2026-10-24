#!/usr/bin/env python3
"""Smoke-test Fengtu live 2.0 endpoints. Never prints FENGTU_APP_KEY."""
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


def _probe_get(url: str, params: dict, headers: dict) -> dict:
    import httpx

    try:
        with httpx.Client(timeout=15.0) as client:
            r = client.get(url, params=params, headers=headers)
        body = None
        try:
            body = r.json()
        except Exception:
            body = None
        result = body.get("result") if isinstance(body, dict) else None
        result_keys = list(result.keys()) if isinstance(result, dict) else None
        return {
            "http_status": r.status_code,
            "ok": r.status_code < 400,
            "json_keys": list(body.keys()) if isinstance(body, dict) else None,
            "result_keys": result_keys,
            "shape": _shape(body) if body is not None else None,
            "biz_status": body.get("status") if isinstance(body, dict) else None,
        }
    except Exception as e:
        return {"error": e.__class__.__name__, "detail": str(e)[:200]}


def _probe_post(url: str, payload: dict, headers: dict) -> dict:
    import httpx

    try:
        with httpx.Client(timeout=15.0) as client:
            r = client.post(
                url,
                json=payload,
                headers={"Content-Type": "application/json", **headers},
            )
        body = None
        try:
            body = r.json()
        except Exception:
            body = None
        result = body.get("result") if isinstance(body, dict) else None
        result_keys = None
        data_keys = None
        if isinstance(result, dict):
            result_keys = list(result.keys())
            data = result.get("data")
            if isinstance(data, dict):
                data_keys = list(data.keys())
        return {
            "http_status": r.status_code,
            "ok": r.status_code < 400,
            "json_keys": list(body.keys()) if isinstance(body, dict) else None,
            "result_keys": result_keys,
            "data_keys": data_keys,
            "shape": _shape(body) if body is not None else None,
            "biz_status": body.get("status") if isinstance(body, dict) else None,
            "addressTrue": (
                result.get("addressTrue") if isinstance(result, dict) else None
            ),
        }
    except Exception as e:
        return {"error": e.__class__.__name__, "detail": str(e)[:200]}


def main() -> int:
    key_set = bool(os.environ.get("FENGTU_APP_KEY", "").strip())
    report: dict = {
        "key_present": key_set,
        "address_len": len(ADDR),
        "endpoints": {
            "geocode": "GET /oplbs/v1/geocode/geo",
            "addressidentify": "POST /opsearch/v1/place/addressidentify",
            "addressResolve": "POST /opquery/v1/addressResolve",
            "addressRealCheck": "POST /opquery/v1/addressRealCheck",
        },
        "addressidentify": {},
        "addressResolve": {},
        "addressRealCheck": {},
        "geocode": {},
        "client_parse": {},
        "client_geocode": {},
    }
    if not key_set:
        report["error"] = "FENGTU_APP_KEY not set"
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 1

    from app.adapters.fengtu_client import (
        ADDRESS_REALCHECK_URL,
        ADDRESS_RESOLVE_URL,
        ADDRESSIDENTIFY_URL,
        FengtuClient,
        GEOCODE_URL,
    )

    key = os.environ["FENGTU_APP_KEY"]
    ak = {"ak": key}

    report["addressidentify"] = _probe_post(
        ADDRESSIDENTIFY_URL,
        {"addresstext": ADDR, "syscode": "SysTEST"},
        ak,
    )
    report["addressResolve"] = _probe_post(
        ADDRESS_RESOLVE_URL, {"address": ADDR}, ak
    )
    report["addressRealCheck"] = _probe_post(
        ADDRESS_REALCHECK_URL, {"address": ADDR}, ak
    )
    report["geocode"] = _probe_get(
        GEOCODE_URL, {"address": ADDR, "cc": 1}, ak
    )

    client = FengtuClient()
    parsed = client.parse(ADDR, {})
    report["client_parse"] = {
        "provider": client.name,
        "parse_source": client.last_parse_source,
        "completeness": parsed.completeness,
        "parse_confidence": parsed.parse_confidence,
        "has_province": bool(parsed.province),
        "has_city": bool(parsed.city),
        "province": parsed.province,
        "city": parsed.city,
        "county": parsed.county,
        "last_error": client.last_error,
    }
    verify = client.verify(parsed)
    report["client_verify"] = {
        "ok": verify.get("ok"),
        "level": verify.get("level"),
        "message": verify.get("message"),
        "reason_code": verify.get("reason_code"),
    }
    geo = client.geocode(parsed)
    report["client_geocode"] = {
        "has_lat": geo.lat is not None,
        "has_lng": geo.lng is not None,
        "lat": geo.lat,
        "lng": geo.lng,
        "confidence": geo.confidence,
        "provider": geo.provider,
        "last_error": client.last_error,
    }

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
        "has_lat": resp.geocode.lat is not None if resp.geocode else False,
        "has_lng": resp.geocode.lng is not None if resp.geocode else False,
        "lat": resp.geocode.lat if resp.geocode else None,
        "lng": resp.geocode.lng if resp.geocode else None,
        "parsed_completeness": resp.parsed.completeness if resp.parsed else None,
        "parsed_province": resp.parsed.province if resp.parsed else None,
        "parsed_city": resp.parsed.city if resp.parsed else None,
    }

    # Health
    try:
        from fastapi.testclient import TestClient
        from app.main import app

        hc = TestClient(app)
        h = hc.get("/health")
        report["health"] = {
            "http_status": h.status_code,
            "body": h.json() if h.status_code == 200 else None,
        }
    except Exception as e:
        report["health"] = {"error": e.__class__.__name__, "detail": str(e)[:200]}

    print(json.dumps(report, ensure_ascii=False, indent=2))

    def _ok(section: dict) -> bool:
        return section.get("http_status") == 200 and section.get("biz_status") in (0, "0")

    live_md = ROOT / "FENGTU_LIVE.md"
    # Rewrite whole doc (avoid appending stale 403 blocks)
    doc = f"""# Fengtu live integration notes

Credential: env `FENGTU_APP_KEY` (AppKey / `ak`). **Never commit, print, or log the value.**

Base: `https://gis-apis.sf-express.com`  
Auth: HTTP header `ak: <FENGTU_APP_KEY>`

## Endpoints used by `app/adapters/fengtu_client.py` (official 2.0, LIVE verified)

| Capability | Method | Path | Body / Query | Sample result fields | Status |
|---|---|---|---|---|---|
| Geocode | GET | `/oplbs/v1/geocode/geo` | `address`, `cc=1`, optional `city` | `xcoord`, `ycoord`, `confidence`, `standardization`, `province`, `city`, `district`, `adcode`, `src_level_desc`, `geo_level_desc` | **LIVE** HTTP 200, status=0 |
| Address identify / parse | POST JSON | `/opsearch/v1/place/addressidentify` | `{{\"addresstext\",\"syscode\"}}` (ak header; ak in body optional) | `result.data`: `province`, `city`, `county`, `town`, `detailaddr`, `adcode` | **LIVE** |
| Address resolve (preferred parse) | POST JSON | `/opquery/v1/addressResolve` | `{{\"address\"}}` | `result.data`: `province`/`city`/`county`/`town`/`vilName`/codes | **LIVE** |
| Authenticity verify | POST JSON | `/opquery/v1/addressRealCheck` | `{{\"address\"}}` | `result.addressTrue` e.g. `\"真实\"` | **LIVE** |

`parse()` prefers `addressResolve`, falls back to `addressidentify`.  
`verify()` uses `addressRealCheck` (`addressTrue`).  
`geocode()` uses `/oplbs/v1/geocode/geo`.

### Removed defaults (403 `consumer_name` forbidden)

- `/pai/api/addressidentify`
- `/all/api/geocode/geo`

## Error → reason codes

| Condition | Reason code |
|---|---|
| HTTP 401/403 or biz status hinting unauthorized (e.g. 113) | `FENGTU_AUTH_FAIL` |
| Other HTTP / network / non-JSON | `FENGTU_HTTP_ERROR` |
| Identify / resolve biz status ≠ 0 | `FENGTU_PARSE_FAIL` |
| Geocode biz status ≠ 0 | `FENGTU_GEOCODE_FAIL` |
| RealCheck biz fail / addressTrue false | `FENGTU_VERIFY_FAIL` |

## Health

`GET /health` → `adapters.fengtu`: `live` if `FENGTU_APP_KEY` set and client constructed, else `mock`.

## Smoke test (keys only; no PII dump / no secrets)

```bash
cd /workspace/address-reachability-service
source .venv/bin/activate
# export FENGTU_APP_KEY=...   # never echo
python scripts/smoke_fengtu_live.py
```

## Integration-time smoke (Asia/Shanghai)

- key_present: `{report['key_present']}`
- addressidentify HTTP: `{report['addressidentify'].get('http_status')}` biz_status=`{report['addressidentify'].get('biz_status')}` result_keys=`{report['addressidentify'].get('result_keys')}` data_keys=`{report['addressidentify'].get('data_keys')}`
- addressResolve HTTP: `{report['addressResolve'].get('http_status')}` biz_status=`{report['addressResolve'].get('biz_status')}` data_keys=`{report['addressResolve'].get('data_keys')}`
- addressRealCheck HTTP: `{report['addressRealCheck'].get('http_status')}` biz_status=`{report['addressRealCheck'].get('biz_status')}` addressTrue=`{report['addressRealCheck'].get('addressTrue')}`
- geocode HTTP: `{report['geocode'].get('http_status')}` biz_status=`{report['geocode'].get('biz_status')}` result_keys=`{report['geocode'].get('result_keys')}`
- client_parse: province=`{report['client_parse'].get('province')}` city=`{report['client_parse'].get('city')}` source=`{report['client_parse'].get('parse_source')}`
- client_geocode: has_lat=`{report['client_geocode'].get('has_lat')}` has_lng=`{report['client_geocode'].get('has_lng')}`
- client_verify: ok=`{report['client_verify'].get('ok')}` level=`{report['client_verify'].get('level')}`
- pipeline mode: `{report['pipeline_fengtu_mode']}` reachable=`{report['pipeline']['reachable']}` status=`{report['pipeline']['status']}` score=`{report['pipeline']['score']}` reasons=`{report['pipeline']['reason_codes']}`
- health fengtu: `{(report.get('health') or {}).get('body', {}).get('adapters', {}).get('fengtu') if isinstance((report.get('health') or {}).get('body'), dict) else None}`

- addressidentify live verified: **{'yes' if _ok(report['addressidentify']) else 'no'}**
- addressResolve live verified: **{'yes' if _ok(report['addressResolve']) else 'no'}**
- addressRealCheck live verified: **{'yes' if _ok(report['addressRealCheck']) else 'no'}**
- geocode live verified: **{'yes' if _ok(report['geocode']) else 'no'}**
"""
    live_md.write_text(doc, encoding="utf-8")

    out = ROOT / "samples" / "fengtu_live_smoke.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
