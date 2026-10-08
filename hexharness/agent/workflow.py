"""Declarative workflow engine: run an ordered list of tool steps, passing values
between them, with for_each iteration and conditional skipping.

PURE orchestration — it never touches the control plane directly. It calls an injected
`step_runner(tool_name, tool_input) -> (ok, output)`; in production that runner routes
EACH step through ControlPlane.authorize() (same chokepoint as the agent loop), so scope,
ROE and HITL approval still apply per step. Templating is string-level: tool outputs are
free text, so `for_each` splits a value into lines/items and `condition` compares strings.
"""
from __future__ import annotations

import re
from typing import Awaitable, Callable

from pydantic import BaseModel, Field

StepRunner = Callable[[str, dict], Awaitable[tuple[bool, str]]]

_TMPL = re.compile(r"\{\{\s*(.*?)\s*\}\}")


class WorkflowStep(BaseModel):
    tool: str = Field(description="Tool name to run for this step.")
    input: dict = Field(default_factory=dict, description="Tool input; strings may use {{var}} templates.")
    output: str | None = Field(default=None, description="Bind this step's result to a variable name.")
    for_each: str | None = Field(default=None,
                                 description="A {{var}} holding a list/multiline value; run the step "
                                             "once per item with {{item}} bound.")
    condition: str | None = Field(default=None,
                                  description="Skip the step unless this is truthy. Supports "
                                              "'{{x}} == text', '!=', 'contains', or bare {{x}} truthiness.")


class RunWorkflowInput(BaseModel):
    steps: list[WorkflowStep]
    variables: dict[str, str] = Field(default_factory=dict,
                                      description="Initial variables available to templates, e.g. {target: app.test}.")


def _resolve_str(s: str, env: dict) -> str:
    return _TMPL.sub(lambda m: _stringify(env.get(m.group(1).strip(), m.group(0))), s)


def _stringify(v) -> str:
    return "\n".join(str(x) for x in v) if isinstance(v, list) else str(v)


def _resolve(obj, env):
    if isinstance(obj, str):
        return _resolve_str(obj, env)
    if isinstance(obj, dict):
        return {k: _resolve(v, env) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_resolve(v, env) for v in obj]
    return obj


def _as_items(value) -> list[str]:
    """Split a bound value into for_each items: a real list stays a list; a string splits
    on newlines then commas (so port_scan/banner output or a CSV both iterate sanely)."""
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    parts = [p.strip() for ln in str(value).splitlines() for p in ln.split(",")]
    return [p for p in parts if p]


def _eval_condition(cond: str, env: dict) -> bool:
    resolved = _resolve_str(cond, env).strip()
    for op in ("==", "!=", "contains"):
        token = f" {op} "
        if token in resolved:
            left, right = (p.strip().strip("'\"") for p in resolved.split(token, 1))
            if op == "==":
                return left == right
            if op == "!=":
                return left != right
            return right in left  # contains
    return bool(resolved) and resolved.lower() not in ("false", "0", "none")


async def run_workflow(data: RunWorkflowInput, step_runner: StepRunner) -> str:
    """Execute the steps in order. Stops at the first failing step. Returns a run log."""
    env: dict = dict(data.variables)
    log: list[str] = []

    for i, step in enumerate(data.steps):
        if step.condition is not None and not _eval_condition(step.condition, env):
            log.append(f"step {i} ({step.tool}): skipped (condition false)")
            continue

        if step.for_each is not None:
            items = _as_items(env.get(step.for_each.strip().strip("{} "), ""))
            if not items:
                log.append(f"step {i} ({step.tool}): for_each empty — nothing to run")
                continue
            outputs: list[str] = []
            for item in items:
                ok, out = await step_runner(step.tool, _resolve(step.input, {**env, "item": item}))
                outputs.append(out)
                log.append(f"step {i} ({step.tool}) [item={item}]: {'ok' if ok else 'FAILED'}")
                if not ok:
                    if step.output:
                        env[step.output] = outputs
                    log.append(f"stopped at step {i}: {out[:300]}")
                    return "\n".join(log)
            if step.output:
                env[step.output] = outputs
        else:
            ok, out = await step_runner(step.tool, _resolve(step.input, env))
            if step.output:
                env[step.output] = out
            log.append(f"step {i} ({step.tool}): {'ok' if ok else 'FAILED'}")
            if not ok:
                log.append(f"stopped at step {i}: {out[:300]}")
                return "\n".join(log)

    log.append(f"workflow complete: {len(data.steps)} step(s)")
    return "\n".join(log)
