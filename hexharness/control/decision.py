from __future__ import annotations

from enum import Enum

from pydantic import BaseModel


class Effect(str, Enum):
    ALLOW = "allow"
    ASK = "ask"
    DENY = "deny"


class Decision(BaseModel):
    effect: Effect
    gate: str  # which gate produced this: scope_guard | mode | roe | budget | hitl
    reason: str = ""

    @property
    def allowed(self) -> bool:
        return self.effect is Effect.ALLOW

    @classmethod
    def allow(cls, gate: str, reason: str = "") -> "Decision":
        return cls(effect=Effect.ALLOW, gate=gate, reason=reason)

    @classmethod
    def ask(cls, gate: str, reason: str = "") -> "Decision":
        return cls(effect=Effect.ASK, gate=gate, reason=reason)

    @classmethod
    def deny(cls, gate: str, reason: str = "") -> "Decision":
        return cls(effect=Effect.DENY, gate=gate, reason=reason)
