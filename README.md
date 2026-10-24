# Address Reachability Service

输入地址 → 返回**可达性 / 可送达（deliverability）**；不可达时给出机器可读原因码 + `path`（字段或流水线阶段）。

- 设计文档（中文）：[DESIGN.md](./DESIGN.md)
- OpenAPI 摘要：[docs/openapi-snippet.yaml](./docs/openapi-snippet.yaml)
- 规则配置：[config/rules.yaml](./config/rules.yaml)
- **无真实丰图 / 顺丰凭证** — 全部为 interface + mock

## 要求

- Python 3.10+
- 依赖见 `requirements.txt`

## 安装与启动

在仓库根目录执行：

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8080 --reload
```

- Swagger UI: <http://127.0.0.1:8080/docs>
- OpenAPI JSON: <http://127.0.0.1:8080/openapi.json>
- Health: `GET /health`

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

中国：`fengtu_mock` + `sf_filter_mock`（筛单 `filterResult` 语义）。  
国际：`intl_mock` + `generic_mock`。

## 重载规则

```bash
curl -s -X POST http://127.0.0.1:8080/v1/admin/reload-rules
```
