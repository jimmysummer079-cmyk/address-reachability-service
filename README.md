# Address Reachability Service

输入地址 → 返回**可达性 / 可送达（deliverability）**；不可达时给出机器可读原因码 + `path`（字段或流水线阶段）。

- 架构（对照 PPT）：[ARCHITECTURE.md](./ARCHITECTURE.md)
- 设计文档（中文）：[DESIGN.md](./DESIGN.md)
- OpenAPI 摘要：[docs/openapi-snippet.yaml](./docs/openapi-snippet.yaml)
- 规则配置：[config/rules.yaml](./config/rules.yaml)
- 丰图：设置环境变量 `FENGTU_APP_KEY` 时走 live SaaS（见 [FENGTU_LIVE.md](./FENGTU_LIVE.md)）；未设置则用 mock
- 顺丰筛单仍为 mock（无开放平台凭证）
- 配置模板：[`.env.example`](./.env.example)（切勿提交 `.env`）

## Architecture

企业「中国区物流地址管理」全景（生成→变更→使用→运营）中，本仓库定位为 **可派送性 / 可达性查询内核**（使用阶段判定 + 可配置规则）。围栏打卡、交接核验、POD、IOC、CRM 回传等见路线图，不在本期实现。

- 架构说明（中文，对照 PPT）：[ARCHITECTURE.md](./ARCHITECTURE.md)
- API/流水线设计：[DESIGN.md](./DESIGN.md)

## 要求

- Python 3.10+
- 依赖见 `requirements.txt`

## 安装与启动

```bash
cd /workspace/address-reachability-service
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8080 --reload
```

- 运营分析台: <http://127.0.0.1:8080/>
- Swagger UI: <http://127.0.0.1:8080/docs>
- OpenAPI JSON: <http://127.0.0.1:8080/openapi.json>
- Health: `GET /health`

若启动时改了端口（例如 uvicorn 默认的 `8000`），把上面地址里的端口换成实际端口。页面始终在服务根路径 `/`，`/docs` 仍是 OpenAPI。

## 运营分析台

浏览器打开 <http://127.0.0.1:8080/> 。这是挂在本服务上的单页控制台（`app/static/`，无单独构建），用来核对可达性判定，不是地址中台。

1. 在「原始地址」粘贴文本，可补国家代码和结构化字段。
2. 点「分析可达性」。页面调用同源 `POST /v1/address/reachability`。
3. 结果区展示整体状态（可送达 / 不可达 / 需人工复核）、`deliverability_score`、`reachable`、解析字段与完整度、原因（code、说明、严重级别、path、rule_id、阶段）、流水线（清洗 → 解析 → 校验 → 地理编码 → 筛单 → 汇总）、地理编码和筛单 `filter_result`（1 人工确认、2 可收派、3 不可收派、4 地址无法确认）。
4. 阻断项的 path 会标到对应字段或阶段。点原因上的「定位」可跳到那一处。
5. 样例按钮直接填入 `samples/requests.json` 里的请求：中国南山可送达、印尼仅路名（城市为空而不可达）、哥伦比亚坐标争议、南非脏文本、巴西简写邮编。

未设置 `FENGTU_APP_KEY` 时，页头健康信息里丰图为「模拟」，中国地址走 `FengtuMockAdapter`，不需要真实密钥。不要把真实密钥写入仓库或提交 `.env`。

## 丰图环境变量

```bash
# copy template; put real AppKey only in local .env (gitignored)
cp .env.example .env
# export FENGTU_APP_KEY=...   # never commit; never echo
```

Live client: `app/adapters/fengtu_client.py`（2.0: `addressResolve` / `addressidentify` / `addressRealCheck` / `oplbs` geocode）。详情见 [FENGTU_LIVE.md](./FENGTU_LIVE.md)。

## 示例 curl

### 健康检查

```bash
curl -s http://127.0.0.1:8080/health | python3 -m json.tool
```

### 印尼不完整地址（期望 unreachable）

```bash
curl -s -X POST http://127.0.0.1:8080/v1/address/reachability \
  -H 'Content-Type: application/json' \
  -d '{
    "address": {
      "country": "ID",
      "raw": "JL. GANDARIA I"
    }
  }' | python3 -m json.tool
```

### 巴西 SP 简写脏分隔符

```bash
curl -s -X POST http://127.0.0.1:8080/v1/address/reachability \
  -H 'Content-Type: application/json' \
  -d '{
    "address": {
      "country": "BR",
      "raw": "Rua,,,,ALAMEDA EUROPA,945,TAMBORE,SANTANA DE PARNAIBA,SP,06.543-325"
    }
  }' | python3 -m json.tool
```

### 南非脏地址

```bash
curl -s -X POST http://127.0.0.1:8080/v1/address/reachability \
  -H 'Content-Type: application/json' \
  -d '{
    "address": {
      "country": "ZA",
      "raw": "Gauteng; NDC BoksburgCnr of Dam and Main RoadAnderboltBoksburg North1459;null;"
    }
  }' | python3 -m json.tool
```

### 哥伦比亚坏地理编码

```bash
curl -s -X POST http://127.0.0.1:8080/v1/address/reachability \
  -H 'Content-Type: application/json' \
  -d '{
    "address": {
      "country": "CO",
      "raw": "Transversal 32 No. 134A-49",
      "sample_tag": "co_bad_geocode"
    }
  }' | python3 -m json.tool
```

更多请求体：`samples/requests.json`。

## 流水线

`clean → parse → validate → geocode/verify → carrier_filter → aggregate`

中国：`fengtu_live`（`FENGTU_APP_KEY` 已设）或 `fengtu_mock` + `sf_filter_mock`。  
国际：`intl_mock` + `generic_mock`。  
`GET /health` 的 `adapters.fengtu` 为 `live` 或 `mock`。

## 重载规则

```bash
curl -s -X POST http://127.0.0.1:8080/v1/admin/reload-rules
```
