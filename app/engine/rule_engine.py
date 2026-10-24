"""Configurable YAML rule engine for address reachability stages."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml

from app.models.schemas import Reason, Severity


BR_UF = {
    "SP": "São Paulo",
    "RJ": "Rio de Janeiro",
    "MG": "Minas Gerais",
    "RS": "Rio Grande do Sul",
    "PR": "Paraná",
    "BA": "Bahia",
    "SC": "Santa Catarina",
    "PE": "Pernambuco",
    "CE": "Ceará",
    "GO": "Goiás",
    "DF": "Distrito Federal",
}


@dataclass
class RuleHit:
    rule_id: str
    action: str
    reason: Reason


@dataclass
class EvalContext:
    """Mutable context passed through pipeline + rules."""

    country: Optional[str] = None
    raw: Optional[str] = None
    cleaned_raw: Optional[str] = None
    fields: dict[str, Any] = field(default_factory=dict)
    sample_tag: Optional[str] = None
    geocode_confidence: float = 1.0
    geocode_dispute_km: float = 0.0
    verify_ok: bool = True
    filter_result: Optional[int] = None
    postal_code_invalid: bool = False
    reasons: list[Reason] = field(default_factory=list)
    blocked: bool = False
    soft_blocked: bool = False
    notes: list[str] = field(default_factory=list)

    def get_field(self, name: str) -> Any:
        if name == "country":
            return self.country
        if name == "raw":
            return self.raw
        return self.fields.get(name)


class RuleEngine:
    def __init__(self, config_path: Path | str):
        self.config_path = Path(config_path)
        self.reload()

    def reload(self) -> None:
        with open(self.config_path, encoding="utf-8") as f:
            self.config = yaml.safe_load(f)
        self.version = str(self.config.get("version", "0"))
        self.rules = list(self.config.get("rules", []))
        self.defaults = dict(self.config.get("defaults", {}))
        self.routing = dict(self.config.get("country_routing", {}))
        self.score_weights = dict(self.config.get("score_weights", {}))

    def router_for(self, country: Optional[str]) -> dict[str, str]:
        if country and country.upper() in self.routing:
            return dict(self.routing[country.upper()])
        return dict(self.routing.get("default", {}))

    def evaluate_stage(self, stage: str, ctx: EvalContext) -> list[RuleHit]:
        hits: list[RuleHit] = []
        for rule in self.rules:
            if rule.get("stage") != stage:
                continue
            if not self._match(rule.get("when", {}), ctx):
                continue
            then = rule.get("then", {})
            severity = Severity(rule.get("severity", "warn"))
            reason = Reason(
                code=then.get("reason_code", "RULE_HIT"),
                message=then.get("message", rule.get("id", "")),
                path=then.get("path", f"stage.{stage}"),
                severity=severity,
                rule_id=rule.get("id"),
                stage=stage,
                details={"action": then.get("action")},
            )
            action = then.get("action", "fail")
            hits.append(RuleHit(rule_id=rule["id"], action=action, reason=reason))
            ctx.reasons.append(reason)
            if action == "fail" or severity == Severity.BLOCK:
                if action != "soft_fail":
                    ctx.blocked = True
            if action == "soft_fail":
                ctx.soft_blocked = True
            self._apply_side_effect(action, then, ctx)
        return hits

    def _match(self, when: dict[str, Any], ctx: EvalContext) -> bool:
        if not when:
            return True
        if "country" in when:
            allowed = [c.upper() for c in when["country"]]
            if not ctx.country or ctx.country.upper() not in allowed:
                return False
        if "raw_contains" in when:
            raw = ctx.raw or ""
            if not any(tok in raw for tok in when["raw_contains"]):
                return False
        if "raw_matches" in when:
            raw = ctx.raw or ""
            if not re.search(when["raw_matches"], raw):
                return False
        if "field_missing" in when:
            for name in when["field_missing"]:
                val = ctx.get_field(name)
                if val is not None and str(val).strip() != "":
                    return False
        if "any_field_missing" in when:
            missing = False
            for name in when["any_field_missing"]:
                val = ctx.get_field(name)
                if val is None or str(val).strip() == "":
                    missing = True
                    break
            if not missing:
                return False
        if "field_present" in when:
            for name in when["field_present"]:
                val = ctx.get_field(name)
                if val is None or str(val).strip() == "":
                    return False
        if "admin1_in" in when:
            a1 = (ctx.fields.get("admin1") or "").upper()
            if a1 not in [x.upper() for x in when["admin1_in"]]:
                return False
        if "postal_code_invalid" in when:
            if bool(ctx.postal_code_invalid) != bool(when["postal_code_invalid"]):
                return False
        if "geocode_confidence_lt" in when:
            if not (ctx.geocode_confidence < float(when["geocode_confidence_lt"])):
                return False
        if "geocode_provider_dispute_km_gt" in when:
            if not (
                ctx.geocode_dispute_km > float(when["geocode_provider_dispute_km_gt"])
            ):
                return False
        if "sample_tag" in when:
            if ctx.sample_tag != when["sample_tag"]:
                return False
        if "verify_ok" in when:
            if bool(ctx.verify_ok) != bool(when["verify_ok"]):
                return False
        if "filter_result_in" in when:
            if ctx.filter_result not in when["filter_result_in"]:
                return False
        return True

    def _apply_side_effect(self, action: str, then: dict, ctx: EvalContext) -> None:
        if action == "strip_tokens":
            raw = ctx.cleaned_raw or ctx.raw or ""
            for tok in ("null", "NULL", ";null;"):
                raw = raw.replace(tok, "")
            raw = re.sub(r";+", ";", raw).strip(" ;")
            ctx.cleaned_raw = raw
            ctx.notes.append("stripped null tokens")
        elif action == "collapse_empty_fields":
            raw = ctx.cleaned_raw or ctx.raw or ""
            raw = re.sub(r",{2,}", ",", raw)
            ctx.cleaned_raw = raw.strip(",")
            ctx.notes.append("collapsed empty CSV fields")
        elif action == "split_glued_tokens":
            raw = ctx.cleaned_raw or ctx.raw or ""
            # Insert space between letter-digit and lower-Upper boundaries
            raw = re.sub(r"([a-z])([A-Z])", r"\1 \2", raw)
            raw = re.sub(r"([A-Za-z])(\d)", r"\1 \2", raw)
            raw = re.sub(r"(\d)([A-Za-z])", r"\1 \2", raw)
            ctx.cleaned_raw = raw
            ctx.notes.append("attempted glued-token split")
        elif action == "expand_admin1":
            a1 = (ctx.fields.get("admin1") or "").upper()
            if a1 in BR_UF:
                ctx.fields["admin1_expanded"] = BR_UF[a1]
                ctx.notes.append(f"expanded UF {a1} → {BR_UF[a1]}")
