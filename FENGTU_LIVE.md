# Fengtu live integration notes

Credential: env `FENGTU_APP_KEY` (AppKey / `ak`). **Never commit, print, or log the value.**

Base: `https://gis-apis.sf-express.com`  
Auth: HTTP header `ak: <FENGTU_APP_KEY>`

## Endpoints used by `app/adapters/fengtu_client.py` (official 2.0, LIVE verified)

| Capability | Method | Path | Body / Query | Sample result fields | Status |
|---|---|---|---|---|---|
| Geocode | GET | `/oplbs/v1/geocode/geo` | `address`, `cc=1`, optional `city` | `xcoord`, `ycoord`, `confidence`, `standardization`, `province`, `city`, `district`, `adcode`, `src_level_desc`, `geo_level_desc` | **LIVE** HTTP 200, status=0 |
| Address identify / parse | POST JSON | `/opsearch/v1/place/addressidentify` | `{"addresstext","syscode"}` (ak header; ak in body optional) | `result.data`: `province`, `city`, `county`, `town`, `detailaddr`, `adcode` | **LIVE** |
| Address resolve (preferred parse) | POST JSON | `/opquery/v1/addressResolve` | `{"address"}` | `result.data`: `province`/`city`/`county`/`town`/`vilName`/codes | **LIVE** |
| Authenticity verify | POST JSON | `/opquery/v1/addressRealCheck` | `{"address"}` | `result.addressTrue` e.g. `"真实"` | **LIVE** |

`parse()` prefers `addressResolve`, falls back to `addressidentify`. A successful response is the only source of province/city/district/road — request structured fields are not merged back in, so an old form fill cannot override the new raw address. If both calls fail, the client falls back to those fields and marks the parse low confidence.  
`verify()` uses `addressRealCheck` (`addressTrue`).  
`geocode()` uses `/oplbs/v1/geocode/geo`.

Unset `FENGTU_APP_KEY` to stay on `FengtuMockAdapter` (local demo). The mock segments the raw Chinese string itself and likewise ignores structured fields once the raw text contains admin or road tokens.

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

- key_present: `True`
- addressidentify HTTP: `200` biz_status=`0` result_keys=`['code', 'paidata', 'src', 'data', 'mark', 'result', 'sn', 'multiple', 'dispatchMark', 'moreThan']` data_keys=`['province', 'city', 'county', 'town', 'adcode', 'citycode', 'detailaddr']`
- addressResolve HTTP: `200` biz_status=`0` data_keys=`['province', 'city', 'county', 'town', 'adcode', 'citycode', 'detailAddr', 'provinceCode', 'cityLevCode', 'countyCode', 'townCode', 'vilName', 'classCode', 'vilcode']`
- addressRealCheck HTTP: `200` biz_status=`0` addressTrue=`真实`
- geocode HTTP: `200` biz_status=`0` result_keys=`['src', 'type', 'precision', 'xcoord', 'ycoord', 'adcode', 'adname', 'province', 'city', 'district', 'confidence', 'source', 'cp', 'standardization', 'time', 'match_level', 'city_adcode', 'geo_source', 'src_level', 'src_level_desc', 'geo_level', 'geo_level_desc', 'match_filter', 'src_address', 'poitype', 'mark', 'mark_desc', 'cp_score', 'poi_count', 'standar_flag', 'standar_word', 'maxDistance', 'uid']`
- client_parse: province=`广东省` city=`深圳市` source=`addressResolve`
- client_geocode: has_lat=`True` has_lng=`True`
- client_verify: ok=`True` level=`address_true`
- pipeline mode: `live` reachable=`True` status=`reachable` score=`97.3` reasons=`[]`
- health fengtu: `live`

- addressidentify live verified: **yes**
- addressResolve live verified: **yes**
- addressRealCheck live verified: **yes**
- geocode live verified: **yes**
