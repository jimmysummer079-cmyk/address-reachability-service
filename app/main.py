"""FastAPI entrypoint — Address Reachability Service."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import RedirectResponse

from app.engine.rule_engine import RuleEngine
from app.models.schemas import HealthResponse, ReachabilityRequest, ReachabilityResponse
from app.pipeline.runner import ReachabilityPipeline

ROOT = Path(__file__).resolve().parents[1]
RULES_PATH = ROOT / "config" / "rules.yaml"

engine = RuleEngine(RULES_PATH)
pipeline = ReachabilityPipeline(engine)

app = FastAPI(
    title="Address Reachability Service",
    description=(
        "输入地址 → 返回可达性（deliverability）。不可达时返回机器可读原因码 + path "
        "（指向字段或流水线阶段）。中国路由丰图 mock；国际国家路由 intl mock；"
        "承运商筛单语义对齐顺丰 filterResult。本脚手架不包含真实丰图/顺丰凭证。"
    ),
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse(url="/docs")


@app.get("/health", response_model=HealthResponse, tags=["ops"])
def health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        rules_version=engine.version,
        adapters={
            "fengtu": "mock",
            "sf_filter": "mock",
            "intl_geocoder": "mock",
        },
    )


@app.post(
    "/v1/address/reachability",
    response_model=ReachabilityResponse,
    tags=["reachability"],
    summary="Query address reachability / deliverability",
)
def check_reachability(body: ReachabilityRequest) -> ReachabilityResponse:
    """Pipeline: clean → parse → validate → geocode/verify → carrier filter → aggregate."""
    return pipeline.run(body)


@app.post("/v1/admin/reload-rules", tags=["ops"], summary="Reload YAML rules from disk")
def reload_rules():
    engine.reload()
    return {"ok": True, "rules_version": engine.version}
