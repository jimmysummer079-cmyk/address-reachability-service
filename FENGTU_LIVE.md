# Fengtu live integration notes

Credential: env `FENGTU_APP_KEY` (AppKey / `ak`). **Never commit, print, or log the value.**

## Endpoints used by `app/adapters/fengtu_client.py`

| Capability | Method | URL | Auth | Status |
|---|---|---|---|---|
| Address identify / parse | POST JSON | `https://gis-apis.sf-express.com/pai/api/addressidentify` | JSON `ak` (+ Header `ak`) | **Attempted live** — see smoke section below |
| Geocode | GET | `https://gis-apis.sf-express.com/all/api/geocode/geo?address=...&cc=1` | Header `ak` | **Attempted live** — see smoke section below |
| Authenticity verify | — | No confirmed public SaaS path for this key | — | **Unverified** — derived from `dispatchMark` / parse confidence |
| Address standardize (dedicated) | — | Product exists on lbs.sfmap.com.cn; cloud path not confirmed | — | **Unverified** — geocode `standardization` field used when present |
| Official private WebService geocode | GET | `http://{IP}:{PORT}/openapi/geocode/geo` | private deploy | **Not used** (not SaaS) |

Sources: third-party blogs mirroring gis-apis.sf-express.com; product list on https://lbs.sfmap.com.cn/ (地址服务: 地理编码 / 验真 / 标准化 / 五级解析). Prefer official console docs when available.

## Error → reason codes

| Condition | Reason code |
|---|---|
| HTTP 401/403 or biz status hinting unauthorized (e.g. 113) | `FENGTU_AUTH_FAIL` |
| Other HTTP / network / non-JSON | `FENGTU_HTTP_ERROR` |
| Identify biz status ≠ 0 | `FENGTU_PARSE_FAIL` |
| Geocode biz status ≠ 0 | `FENGTU_GEOCODE_FAIL` |

## Health

`GET /health` → `adapters.fengtu`: `live` if `FENGTU_APP_KEY` set and client constructed, else `mock`.

## Smoke test (keys only; no PII dump)

Run after setting the key in the environment (not in git):

在仓库根目录执行：

```bash
source .venv/bin/activate
python scripts/smoke_fengtu_live.py
```

Results of the integration-time smoke are appended below by the smoke script / agent.

## Integration-time smoke (Asia/Shanghai)

- key_present: `True`
- addressidentify HTTP: `403` biz_status=`None` keys=`['message']`
- geocode HTTP: `403` biz_status=`None` keys=`['message']`
- pipeline mode: `live` status=`unreachable` reasons=`['ADDR_PROVINCE_MISSING', 'FENGTU_AUTH_FAIL', 'FENGTU_AUTH_FAIL', 'VERIFY_FAIL', 'FENGTU_AUTH_FAIL', 'GEO_LOW_CONF', 'CARRIER_ADDR_UNCONFIRMED']`

- addressidentify live verified: **no**
- geocode live verified: **no**

