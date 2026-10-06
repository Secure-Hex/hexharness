"""Composition root. Assembles the control plane, event backbone, tools and loop from
an engagement file. One place wires everything so the CLI, tests and (later) the daemon
share identical assembly.
"""
from __future__ import annotations

from pathlib import Path

from hexharness.agent.context import ExecContext
from hexharness.agent.loop import AgentLoop
from hexharness.control.hitl import Approver
from hexharness.control.kill_switch import KillSwitch
from hexharness.control.plane import ControlPlane
from hexharness.control.policy import Mode
from hexharness.engagement import Engagement
from hexharness.events.bus import EventBus
from hexharness.events.store import EventStore
from hexharness.events.types import EventType
from hexharness.evidence.store import EvidenceStore
from hexharness.providers.base import LLMProvider
from hexharness.sandbox.executor import SandboxExecutor
from hexharness.tools.native import CweLookupTool, DnsLookupTool, PortScanTool
from hexharness.tools.registry import ToolRegistry


def default_registry() -> ToolRegistry:
    from pathlib import Path

    from hexharness.knowledge import KnowledgeSearchTool, MitreAttackTool
    from hexharness.skills.engine import SkillRegistry
    from hexharness.skills.tool import SkillLookupTool

    reg = ToolRegistry()
    executor = SandboxExecutor()
    # passive, no scope needed
    reg.register(CweLookupTool())
    reg.register(MitreAttackTool())
    reg.register(KnowledgeSearchTool())
    skills = SkillRegistry().discover(Path(__file__).parent / "skills" / "library")
    reg.register(SkillLookupTool(skills))
    # scope-sensitive / sandboxed
    reg.register(DnsLookupTool())
    reg.register(PortScanTool(executor))
    return reg


class Engine:
    def __init__(
        self, *, engagement: Engagement, events: EventStore, evidence: EvidenceStore,
        control: ControlPlane, registry: ToolRegistry, ctx: ExecContext, kill_switch: KillSwitch,
    ):
        self.engagement = engagement
        self.events = events
        self.evidence = evidence
        self.control = control
        self.registry = registry
        self.ctx = ctx
        self.kill_switch = kill_switch

    @classmethod
    def from_engagement(
        cls, path: str | Path, *, provider: LLMProvider, requested_mode: Mode | None = None,
        approver: Approver | None = None, subagent: str = "main", db: str = ":memory:",
        registry: ToolRegistry | None = None, kill_trigger_file: str | Path | None = None,
    ) -> "Engine":
        return cls._assemble(
            Engagement.load(path), provider=provider, requested_mode=requested_mode,
            approver=approver, subagent=subagent, db=db, registry=registry,
            kill_trigger_file=kill_trigger_file,
        )

    @classmethod
    def bootstrap(cls, *, out_dir: str | Path = "engagements", approver: Approver | None = None,
                  db: str = ":memory:") -> "Engine":
        """A locked engine whose ONLY capability is drafting a new engagement from a
        natural-language brief. Empty scope, report-only autonomy, passive ceiling — it
        cannot scan or exploit anything. Used by `hexharness init` before a real
        engagement exists; the drafted file still needs human activation."""
        from hexharness.tools.native.engagement_tools import EngagementDraftTool

        eng = Engagement.model_validate({
            "name": "bootstrap", "client": "",
            "scope": {}, "roe": {"max_risk": "passive", "max_autonomy": "report", "max_phase": "recon"},
        })
        reg = ToolRegistry()
        reg.register(EngagementDraftTool(out_dir))
        from hexharness.control.policy import Autonomy, Phase

        return cls._assemble(
            eng, provider=None, requested_mode=Mode(autonomy=Autonomy.REPORT, phase=Phase.RECON),
            approver=approver, subagent="bootstrap", db=db, registry=reg, kill_trigger_file=None,
        )

    @classmethod
    def _assemble(
        cls, eng: Engagement, *, provider: LLMProvider | None, requested_mode: Mode | None,
        approver: Approver | None, subagent: str, db: str, registry: ToolRegistry | None,
        kill_trigger_file: str | Path | None,
    ) -> "Engine":
        bus = EventBus()
        # Tracing is a projection of the event stream: attach BEFORE the first append.
        # No-op if opentelemetry isn't installed; a broken tracer can't break the stream.
        from hexharness.observability.otel import OTelProjector

        OTelProjector().attach(bus)
        events = EventStore(db, bus=bus)
        evidence = EvidenceStore(db, events=events)
        control = ControlPlane(
            scope_guard=eng.scope_guard(), roe=eng.roe_policy(),
            budget=eng.budget_tracker(), events=events, approver=approver,
        )
        mode = eng.clamp(requested_mode or Mode())  # active mode = min(requested, ROE)
        ctx = ExecContext(engagement_id=eng.name, subagent_id=subagent, mode=mode)

        async def _checkpoint() -> None:
            await events.append(EventType.CHECKPOINT, {"reason": "kill-switch", "subagent": subagent})

        kill = KillSwitch(trigger_file=kill_trigger_file, checkpoint=_checkpoint)
        self = cls(
            engagement=eng, events=events, evidence=evidence, control=control,
            registry=registry or default_registry(), ctx=ctx, kill_switch=kill,
        )
        return self

    def loop(self, *, provider: LLMProvider, model: str | None = None) -> AgentLoop:
        return AgentLoop(
            provider=provider, control=self.control, registry=self.registry,
            events=self.events, ctx=self.ctx, model=model, kill_switch=self.kill_switch,
        )
