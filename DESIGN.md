# 地址可达性应用服务设计（Deliverability API）

> **路径：** `/workspace/address-reachability-service/`  
> **版本：** 0.1.0 · **更新：** 2026-10-24（Asia/Shanghai）  
> **定位：** 对外 REST：**输入地址 → 返回可达性**；不可达时返回**原因码 + 出错字段/阶段 path**。  
> **范围：** 本期以 **可达性 / 可送达（deliverability）** 为主；POD/乱签收双分中的签收风险见既有文档，本 API **不返回 PODRiskScore**。  
> **关联：** `/workspace/fengtu-address-risk-solution.md`、`/workspace/global-address-quality-fengtu-ops.md`

---

## 1. 目标与非目标

| 目标 | 说明 |
|------|------|
| 单一查询接口 | `POST /v1/address/reachability` |
| 失败可定位 | 每个 reason 含 `code`（机器可读）+ `message`（人读）+ `path`（如 `address.city` / `stage.geocode`）+ 可选 `rule_id` |
| 规则可配置 | YAML/JSON 规则按 **stage** 绑定，支持国别条件 |
| 国家路由 | **CN → 丰图（接口+mock）**；**国际 → 国际解析/地理编码 mock**；承运商筛单语义对齐顺丰 |
| SF 机制对齐 | 筛单 `filterResult`、地址验真、地址层级/完整性检查 |

| 非目标（本期） |
|----------------|
| 真实丰图 / 顺丰开放平台凭证与联调（仅接口抽象 + mock） |
| POD / 乱签收评分与证据链 |
| 替代承运商核心运单系统 |

---

## 2. 总体流水线

```text
clean → parse → validate → geocode/verify → carrier_filter → aggregate
```

| 阶段 | 职责 | 典型 path 前缀 |
|------|------|----------------|
| **clean** | 去 `null`、折叠空分隔符、词粘连恢复、控制字符 | `address.raw` |
| **parse** | 结构化字段；国别词典（如 BR 的 UF=SP）；完整性 | `address.*` |
| **validate** | 邮编格式/国别正则、必填门槛 | `address.postal_code` 等 |
| **geocode/verify** | CN：丰图验真+地理编码（GCJ-02）；INT：国际编码（WGS84）+ 置信度/双源争议 | `stage.geocode` / `stage.verify` |
| **carrier_filter** | 对齐顺丰筛单：是否在收派范围 | `stage.carrier_filter` |
| **aggregate** | `deliverability_score` + `status` ∈ {reachable, unreachable, needs_review} | — |

**国家路由（配置见 `config/rules.yaml` → `country_routing`）：**

```text
CN  → parser/geocoder=fengtu, carrier_filter=sf_express
*   → parser/geocoder=intl_mock, carrier_filter=generic_mock
```

---

## 3. REST API 契约

### 3.1 健康检查

`GET /health` → `{ "status": "ok", "rules_version": "...", "adapters": { "fengtu": "mock", ... } }`

### 3.2 可达性查询

`POST /v1/address/reachability`  
`Content-Type: application/json`

**请求体：**

```json
{
  "address": {
    "country": "ID",
    "raw": "JL. GANDARIA I",
    "province": null,
    "admin1": null,
    "city": null,
    "locality": null,
    "road": null,
    "house_number": null,
    "postal_code": null,
    "sample_tag": null,
    "lat": null,
    "lng": null
  },
  "carrier": "sf_express",
  "product_code": null,
  "options": {}
}
```

- `country`：ISO 3166-1 alpha-2，**强烈建议必填**（缺失则 `ADDR_COUNTRY_MISSING`）。
- 可只传 `raw`，也可传结构化字段；结构化优先，raw 用于清洗与兜底解析。
- `sample_tag`：脚手架夹具标签（如 `co_bad_geocode`），生产可忽略。

**响应体（成功 HTTP 200，业务是否可达看 `reachable` / `status`）：**

```json
{
  "status": "unreachable",
  "reachable": false,
  "deliverability_score": 18.5,
  "reasons": [
    {
      "code": "ADDR_INCOMPLETE",
      "message": "Indonesia address has road only ...",
      "path": "address.city",
      "severity": "block",
      "rule_id": "PARSE_INCOMPLETE_ID",
      "stage": "parse",
      "details": { "action": "fail" }
    }
  ],
  "parsed": { "...": "..." },
  "geocode": { "...": "..." },
  "carrier_filter": {
    "filter_result": 4,
    "remark": "incomplete",
    "carrier": "generic_mock"
  },
  "pipeline": [ { "stage": "clean", "ok": true, "duration_ms": 0.4 } ],
  "rules_version": "1.0.0",
  "request_id": "uuid"
}
```

交互文档：服务启动后访问 `/docs`（Swagger UI）或 `/openapi.json`；静态摘要见 `docs/openapi-snippet.yaml`。

---

## 4. 原因码（Reason Codes）

约定：

- **`code`**：`SCREAMING_SNAKE`，稳定、可告警、可统计。
- **`message`**：给人看的说明（可 i18n；本期英文/中英混合以规则配置为准）。
- **`path`**：JSON Pointer 风格的逻辑路径：
  - 字段问题：`address.country` / `address.city` / `address.postal_code` / `address.raw` …
  - 阶段问题：`stage.clean` / `stage.parse` / `stage.validate` / `stage.geocode` / `stage.verify` / `stage.carrier_filter`
- **`rule_id`**：命中的配置规则 ID，便于运营改规则而不改码表。
- **`severity`**：`info` | `warn` | `block`（`block` → 通常 `unreachable`）。

| code | 典型 path | 含义 |
|------|-----------|------|
| `ADDR_DIRTY_NULL_TOKEN` | `address.raw` | 原文含 null 占位 |
| `ADDR_DIRTY_SEPARATOR` | `address.raw` | 空分隔符粘连（如 BR `,,,,`） |
| `ADDR_DIRTY_GLUED_TOKENS` | `address.raw` | 词粘连（如 ZA `RoadAnderbolt`） |
| `ADDR_COUNTRY_MISSING` | `address.country` | 缺国家，无法路由 |
| `ADDR_PROVINCE_MISSING` | `address.province` | 中国缺省 |
| `ADDR_INCOMPLETE` | `address.city` 等 | 完整性不足（如 ID 仅道路） |
| `ADDR_ADMIN1_ABBREV` | `address.admin1` | 州/省简写已展开（信息级） |
| `ADDR_POSTCODE_INVALID` | `address.postal_code` | 邮编非法 |
| `VERIFY_FAIL` | `stage.verify` | 丰图风格验真失败 |
| `GEO_LOW_CONF` | `stage.geocode` | 地理编码置信度低 |
| `GEO_PROVIDER_DISPUTE` | `stage.geocode` | 双源距离超阈值 |
| `GEO_BAD_CANDIDATE` | `stage.geocode` | 坏候选点（CO 样例） |
| `CARRIER_OUT_OF_SERVICE` | `stage.carrier_filter` | 筛单 `filterResult=3` |
| `CARRIER_ADDR_UNCONFIRMED` | `stage.carrier_filter` | 筛单 `filterResult=4` |
| `CARRIER_MANUAL_CONFIRM` | `stage.carrier_filter` | 筛单 `filterResult=1` |

与既有方案对齐的码：`ADDR_PARSE_FAIL` / `VERIFY_FAIL` / `GEO_LOW_CONF` / `DOORSTEP_UNREACHABLE` / `CARRIER_OUT_OF_SERVICE`（上门不可达可在接入真实丰图「上门可投递」后扩展）。

---

## 5. 可配置规则模型

文件：`config/rules.yaml`（亦可等价 JSON）。

```yaml
version: "1.0.0"
defaults:
  min_deliverability_score: 70
  geocode_min_confidence: 0.55
country_routing:
  CN: { parser: fengtu, geocoder: fengtu, carrier_filter: sf_express }
  default: { parser: libpostal_mock, geocoder: intl_mock, carrier_filter: generic_mock }
rules:
  - id: PARSE_INCOMPLETE_ID
    stage: parse
    severity: block
    when:
      country: ["ID"]
      any_field_missing: ["city", "locality", "postal_code", "admin2"]
      field_present: ["road"]
    then:
      action: fail
      reason_code: ADDR_INCOMPLETE
      path: address.city
      message: "..."
score_weights:
  completeness: 0.30
  parse_confidence: 0.15
  verify: 0.20
  geocode_confidence: 0.20
  carrier_in_service: 0.15
```

**匹配条件（`when`）示例：** `country`、`raw_contains`、`raw_matches`、`field_missing`、`any_field_missing`、`field_present`、`admin1_in`、`postal_code_invalid`、`geocode_confidence_lt`、`geocode_provider_dispute_km_gt`、`sample_tag`、`verify_ok`、`filter_result_in`。

**动作（`then.action`）：** `fail` / `soft_fail` / `strip_tokens` / `collapse_empty_fields` / `split_glued_tokens` / `expand_admin1`。

热加载：`POST /v1/admin/reload-rules`（脚手架级）。

---

## 6. 顺丰启发机制（筛单 / 验真 / 层级）

### 6.1 筛单（Filter Order）— `filterResult`

客户系统主动请求：寄/收地址是否在顺丰收派范围。

| filterResult | 含义 | 本服务映射 |
|--------------|------|------------|
| 1 | 人工确认 | `CARRIER_MANUAL_CONFIRM` → `needs_review` |
| 2 | 可收派 | 承运商维度通过 |
| 3 | 不可收派 | `CARRIER_OUT_OF_SERVICE`；`remark`：1 收方超范围 / 2 派方超范围 / 3 其它 |
| 4 | 地址无法确认 | `CARRIER_ADDR_UNCONFIRMED` |

公开入口与规范（**无凭证、不代为调用生产**）：

- 顺丰开放平台：<https://open.sf-express.com/>
- 丰桥 / 统一接入规范 PDF（含 `EXP_RECE_FILTER_ORDER_BSP`）：<https://qiao.sf-express.com/>
- 服务码常见名：`EXP_RECE_FILTER_ORDER_BSP`（新网关）/ 历史 `OrderFilterService`

本仓库：`app/adapters/sf_filter_mock.py` 仅 mock 上述语义。

### 6.2 地址验真与层级（Verify / Level）

中国侧对齐丰图能力叙事（标准化、四级/五级、验真、地理/逆地理、上门可投递等）：

- 地址服务产品页：<https://lbs.sfmap.com.cn/product/ft-address-services>
- Geocoder（示例为国内地址，`position_gcj`）：<https://lbs.sfmap.com.cn/sfmapsdk-doc/ftmap_2d_jsapi/Geocoder.html>
- 逆地理：<https://lbs.sfmap.com.cn/sfmapsdk-doc/ftmap_webservice_api/03-reverse-geocoding.html>
- 平台首页：<https://lbs.sfmap.com.cn/>

脚手架：`FengtuMockAdapter.verify()` 在缺省/市或命中「虚假」关键字时返回失败 → `VERIFY_FAIL` @ `stage.verify`。  
**诚实声明：无真实 appKey/secret；未联调生产丰图。**

### 6.3 与「双评分」的边界

```text
本 API  = Deliverability / Reachability
不做    = PODRiskScore（签收真实性）
```

高可送达仍可能高签收风险——那是另一条控制链，见 `fengtu-address-risk-solution.md`。

---

## 7. 验收样例（全球脏数据形态）

| 标签 | 国家 | 原文特征 | 期望主因 path |
|------|------|----------|---------------|
| `za_dirty` | ZA | `;null;`、词粘连、NDC 噪声 | `address.raw`（清洁警告）+ 可能仍可部分结构化 |
| `br_abbrev_sp` | BR | `,,,,`、UF=`SP`、CEP `06.543-325` | 清洁 + `address.admin1` 展开；规范 CEP 后可较高分 |
| `id_incomplete` | ID | 仅 `JL. GANDARIA I` | `address.city` / `ADDR_INCOMPLETE` → unreachable |
| `co_bad_geocode` | CO | 坏点 vs 业务正确点相距数十公里 | `stage.geocode` / `GEO_BAD_CANDIDATE` 或 `GEO_LOW_CONF` |
| `cn_ok_mock` | CN | 完整省市 | mock 可达（演示正向路径） |

样例请求：`samples/requests.json`。

---

## 8. 模块结构

```text
address-reachability-service/
  DESIGN.md                 # 本文
  README.md                 # 运行方式
  requirements.txt
  config/rules.yaml         # 可配置规则
  docs/openapi-snippet.yaml
  samples/requests.json
  app/
    main.py                 # FastAPI
    models/schemas.py
    engine/rule_engine.py
    pipeline/runner.py
    adapters/
      fengtu_mock.py
      sf_filter_mock.py
      intl_mock.py
```

---

## 9. 后续接入真实依赖（指引，非本期交付）

1. 实现 `FengtuClient`（签名、超时、熔断），替换 mock；坐标系在业务层明确 GCJ-02 vs WGS84。  
2. 实现 `SFFilterClient`（`partnerID` / `msgDigest` 等按开放平台规范），映射 `filterResult`/`remark`。  
3. 国际侧接入 Loqate / Google Address Validation / Melissa / Smarty 之一，保留双源距离阈值规则。  
4. 规则配置迁配置中心；原因码表版本化；与 OMS 拦截/改址工单打通。

---

## 10. 合规与安全

- 不在仓库或日志中写入真实丰图/顺丰密钥。  
- 地址属个人信息，日志需脱敏（门牌/电话）。  
- 跨境地理编码遵守供应商 ToS 与当地地图法规；中国生产主链路不用 OSM 冒充丰图。
