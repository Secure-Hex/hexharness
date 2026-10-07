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


def default_registry(*, vault=None, secret_requester=None, workspace: str | Path | None = None,
                     evidence=None, events=None, sandbox_image: str = "hexharness/kali:latest") -> ToolRegistry:
    from pathlib import Path

    from hexharness.control.secrets import DenySecretRequester
    from hexharness.control.vault import Vault
    from hexharness.knowledge import KnowledgeSearchTool, MitreAttackTool
    from hexharness.skills.engine import SkillRegistry
    from hexharness.skills.tool import SkillLookupTool
    from hexharness.tools.native.exec import ExecCommandTool
    from hexharness.tools.native.extend import McpConnectTool, SkillInstallTool
    from hexharness.tools.native.fs import FileReadTool, FileWriteTool
    from hexharness.tools.native.binary import BinaryInfoTool, ChecksecTool, DisassembleTool
    from hexharness.tools.native.browser import BrowserTool
    from hexharness.tools.native.postman import PostmanListTool, PostmanRunTool
    from hexharness.tools.native.recon import DnsEnumTool, SmbEnumTool, WhoisLookupTool
    from hexharness.tools.native.services import (
        BannerGrabTool, FtpCheckTool, HttpProbeTool, SshInfoTool,
    )
    from hexharness.tools.native.shodan import ShodanHostTool
    from hexharness.tools.native.websearch import WebSearchTool

    reg = ToolRegistry()
    executor = SandboxExecutor()
    vault = vault or Vault()
    secret_requester = secret_requester or DenySecretRequester()
    workspace = Path(workspace or ".hexharness/workspace")
    library = Path(__file__).parent / "skills" / "library"
    skills = SkillRegistry().discover(library)

    # passive, no scope needed
    reg.register(CweLookupTool())
    reg.register(MitreAttackTool())
    reg.register(KnowledgeSearchTool())
    reg.register(SkillLookupTool(skills))
    # OSINT web search (ACTIVE, not scope-sensitive): free ddgs default, paid keys via vault
    reg.register(WebSearchTool(vault))
    if evidence is not None:
        from hexharness.tools.native.evidence_tools import RecordFindingTool

        reg.register(RecordFindingTool(evidence))  # agent logs findings as CANDIDATE
    # Model may PROPOSE an engagement/scope; activation is a human action in the TUI.
    from hexharness.tools.native.engagement_tools import EngagementDraftTool

    reg.register(EngagementDraftTool("engagements", events=events))
    # file / code I/O, workspace-confined (write gated: INTRUSIVE + approval)
    reg.register(FileReadTool(workspace))
    reg.register(FileWriteTool(workspace))
    # command execution, sandboxed (DESTRUCTIVE + approval)
    reg.register(ExecCommandTool(executor, image=sandbox_image, workspace=str(workspace)))
    # runtime extensibility, model-driven (both ACTIVE/INTRUSIVE + approval)
    reg.register(SkillInstallTool(skills, library))
    reg.register(McpConnectTool(reg, vault, secret_requester))
    # API testing via Postman collections (list passive; run intrusive + scope-checked)
    reg.register(PostmanListTool())
    reg.register(PostmanRunTool())
    # scope-sensitive / sandboxed network
    reg.register(DnsLookupTool())
    reg.register(PortScanTool(executor, image=sandbox_image))
    # network service probes (ACTIVE, scope-sensitive — Scope Guard checks the host/url)
    reg.register(BannerGrabTool())
    reg.register(FtpCheckTool())
    reg.register(SshInfoTool())
    reg.register(HttpProbeTool())
    reg.register(BrowserTool(workspace))  # Playwright: interact + screenshots to the workspace
    # recon via kali sandbox (scope-sensitive)
    reg.register(DnsEnumTool())            # native resolver (dnspython), no sandbox
    reg.register(WhoisLookupTool())        # native WHOIS over TCP/43, no sandbox
    reg.register(SmbEnumTool(executor, image=sandbox_image))
    reg.register(ShodanHostTool(vault))  # needs SHODAN_API_KEY → demos the out-of-band secret flow
    # binary / reversing static analysis, workspace-confined (ACTIVE, host subprocess)
    reg.register(BinaryInfoTool(workspace))
    reg.register(ChecksecTool(workspace))
    reg.register(DisassembleTool(workspace))
    return reg


class Engine:
    def __init__(
        self, *, engagement: Engagement, events: EventStore, evidence: EvidenceStore,
        control: ControlPlane, registry: ToolRegistry, ctx: ExecContext, kill_switch: KillSwitch,
        vault=None,
    ):
        self.engagement = engagement
        self.events = events
        self.evidence = evidence
        self.control = control
        self.registry = registry
        self.ctx = ctx
        self.kill_switch = kill_switch
        self.vault = vault

    @classmethod
    def from_engagement(
        cls, path: str | Path, *, provider: LLMProvider, requested_mode: Mode | None = None,
        approver: Approver | None = None, subagent: str = "main", db: str = ":memory:",
        registry: ToolRegistry | None = None, kill_trigger_file: str | Path | None = None,
        vault=None, secret_requester=None,
    ) -> "Engine":
        return cls._assemble(
            Engagement.load(path), provider=provider, requested_mode=requested_mode,
            approver=approver, subagent=subagent, db=db, registry=registry,
            kill_trigger_file=kill_trigger_file, vault=vault, secret_requester=secret_requester,
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
    def blank(cls, *, approver: Approver | None = None, secret_requester=None,
              db: str = ":memory:", vault=None) -> "Engine":
        """An UNCONFIGURED engine: empty scope, report-only ceiling, but the FULL tool
        registry (incl. the events-wired engagement_draft tool). The model can only draft
        an engagement — everything else is denied fail-closed by scope/ROE. Used by the TUI
        when launched without --engagement; once the operator approves a draft, the caller
        rebuilds a file-backed engine from the drafted file."""
        from hexharness.control.policy import Autonomy, Phase

        eng = Engagement.model_validate({
            "name": "unconfigured", "client": "",
            "scope": {}, "roe": {"max_risk": "passive", "max_autonomy": "report", "max_phase": "recon"},
        })
        return cls._assemble(
            eng, provider=None, requested_mode=Mode(autonomy=Autonomy.REPORT, phase=Phase.RECON),
            approver=approver, subagent="main", db=db, registry=None,
            kill_trigger_file=None, vault=vault, secret_requester=secret_requester,
        )

    @classmethod
    def _assemble(
        cls, eng: Engagement, *, provider: LLMProvider | None, requested_mode: Mode | None,
        approver: Approver | None, subagent: str, db: str, registry: ToolRegistry | None,
        kill_trigger_file: str | Path | None, vault=None, secret_requester=None,
    ) -> "Engine":
        from hexharness.control.vault import Vault

        vault = vault or Vault()
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
            vault=vault, secret_requester=secret_requester,
        )
        mode = eng.clamp(requested_mode or Mode())  # active mode = min(requested, ROE)
        ctx = ExecContext(engagement_id=eng.name, subagent_id=subagent, mode=mode)

        async def _checkpoint() -> None:
            await events.append(EventType.CHECKPOINT, {"reason": "kill-switch", "subagent": subagent})

        kill = KillSwitch(trigger_file=kill_trigger_file, checkpoint=_checkpoint)
        # Per-engagement workspace so file/exec tools are isolated per engagement.
        slug = "".join(c if c.isalnum() or c in "-_" else "-" for c in eng.name.lower())
        workspace = Path(".hexharness") / slug / "workspace"
        reg = registry if registry is not None else default_registry(
            vault=vault, secret_requester=secret_requester, workspace=workspace,
            evidence=evidence, events=events, sandbox_image=eng.sandbox_image,
        )
        return cls(
            engagement=eng, events=events, evidence=evidence, control=control,
            registry=reg, ctx=ctx, kill_switch=kill, vault=vault,
        )

    async def apply_engagement(self, engagement: Engagement, *, approved_by: str) -> None:
        """Swap the active scope/ROE to a new engagement at runtime. The ONLY sanctioned
        way to change scope while running — invoked solely by an explicit human approval
        (never by a tool/the model), and audited as SCOPE_CHANGED. Keeps the event log,
        evidence, budget spend, and conversation; replaces scope_guard + ROE in place."""
        self.engagement = engagement
        self.control.scope_guard = engagement.scope_guard()
        self.control.roe = engagement.roe_policy()
        new_budget = engagement.budget_tracker()
        new_budget.tokens_used = self.control.budget.tokens_used  # carry spend across the change
        new_budget.usd_used = self.control.budget.usd_used
        self.control.budget = new_budget
        # Update the sandbox image live so exec_command uses the new engagement's image.
        exec_tool = self.registry.get("exec_command")
        if exec_tool is not None and hasattr(exec_tool, "image"):
            exec_tool.image = engagement.sandbox_image
        self.ctx = ExecContext(
            engagement_id=engagement.name, subagent_id=self.ctx.subagent_id,
            mode=engagement.clamp(self.ctx.mode), now=self.ctx.now,  # re-clamp to the new ROE
        )
        await self.events.append(EventType.SCOPE_CHANGED, {
            "engagement": engagement.name, "approved_by": approved_by,
            "scope": {"cidrs": list(engagement.scope.cidrs), "domains": list(engagement.scope.domains),
                      "exclusions": list(engagement.scope.exclusions)},
            "max_risk": engagement.roe.max_risk,
        })

    def loop(self, *, provider: LLMProvider, model: str | None = None,
             on_text=None, on_thinking=None) -> AgentLoop:
        return AgentLoop(
            provider=provider, control=self.control, registry=self.registry,
            events=self.events, ctx=self.ctx, model=model, kill_switch=self.kill_switch,
            on_text=on_text, on_thinking=on_thinking,
        )
