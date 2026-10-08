"""Build and validate an engagement.yaml from a structured spec.

This is the authoring side of the engagement. It NEVER activates anything — it only
renders validated YAML. Activation stays a human-confirmed step (the agent cannot grant
itself scope/ROE at runtime; invariants #3/#4). The spec is validated by actually
constructing the runtime Scope Guard and ROE from it, so a bad CIDR or unknown enum
fails here, loudly, before any file is written.
"""
from __future__ import annotations

from pathlib import Path

import json

import yaml
from pydantic import BaseModel, Field, field_validator

from hexharness.engagement import Engagement


def _coerce_json(v):
    """Some models serialize a nested object as a JSON STRING instead of a dict/list.
    Parse it so `scope`/`roe`/`budget`/`windows` validate either way; leave non-JSON
    strings untouched so normal validation still raises a clear error."""
    if isinstance(v, str):
        try:
            return json.loads(v)
        except (json.JSONDecodeError, ValueError):
            return v
    return v


class ScopeSpec(BaseModel):
    cidrs: list[str] = Field(default_factory=list)
    domains: list[str] = Field(default_factory=list)
    exclusions: list[str] = Field(default_factory=list)


class WindowSpec(BaseModel):
    start: str  # "HH:MM"
    end: str


class RoeSpec(BaseModel):
    max_risk: str = "active"
    max_autonomy: str = "interactive"
    max_phase: str = "enumeration"
    windows: list[WindowSpec] = Field(default_factory=list)

    _parse_windows = field_validator("windows", mode="before")(_coerce_json)


class BudgetSpec(BaseModel):
    max_tokens: int | None = None
    max_usd: float | None = None
    max_seconds: float | None = None


class EngagementSpec(BaseModel):
    name: str
    client: str = ""
    scope: ScopeSpec = Field(default_factory=ScopeSpec)
    roe: RoeSpec = Field(default_factory=RoeSpec)
    budget: BudgetSpec = Field(default_factory=BudgetSpec)
    report_template: str = "default.html.j2"
    sandbox_image: str = "hexharness/kali:latest"
    hardware_access: bool = False  # pass host USB + wireless into the sandbox (opt-in)

    # Tolerate models that pass a nested object as a JSON string (see _coerce_json).
    _parse_nested = field_validator("scope", "roe", "budget", mode="before")(_coerce_json)


def validate_spec(spec: EngagementSpec) -> Engagement:
    """Round-trip through the real Engagement model AND build the runtime guards, so an
    invalid scope/ROE raises now rather than at engagement load time."""
    eng = Engagement.model_validate(spec.model_dump())
    eng.scope_guard()   # raises on a bad CIDR/exclusion
    eng.roe_policy()    # raises on an unknown risk/autonomy/phase enum or bad time window
    return eng


def render_yaml(spec: EngagementSpec) -> str:
    validate_spec(spec)
    return yaml.safe_dump(spec.model_dump(), sort_keys=False, default_flow_style=False)


def _slug(name: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "-" for c in name.strip().lower())


def write_engagement(spec: EngagementSpec, out_dir: str | Path = "engagements") -> Path:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{_slug(spec.name)}.engagement.yaml"
    path.write_text(render_yaml(spec))
    return path
