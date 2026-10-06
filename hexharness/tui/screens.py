"""Modal screens: provider selection / registration, the HITL approval prompt, the
masked secret-input prompt, and a read-only capabilities panel."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from textual import on, work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, ListItem, ListView, SelectionList, Static

from hexharness.control.policy import Autonomy, Mode, Phase
from hexharness.tui.providers import CATALOG, ProviderEntry, detect, model_for, register

# Skills live next to the package: hexharness/skills/library.
_SKILLS_LIBRARY = Path(__file__).resolve().parent.parent / "skills" / "library"


def _badge(e: ProviderEntry) -> str:
    return "●" if detect(e) else "○"


def _row(e: ProviderEntry) -> str:
    state = "configured" if detect(e) else "needs key"
    return f"{_badge(e)}  {e.label}  —  {model_for(e)}  ({state})"


class ProviderScreen(ModalScreen[dict]):
    """Pick the active provider (or build a Router) and register missing keys in-process.

    Dismisses with a selection dict the app turns into a provider:
      {"kind": "provider", "keys": ["anthropic"], "model": "<override or '' >"}
      {"kind": "router",   "keys": ["google", "anthropic"], "model": ""}
    or nothing (None) on cancel.
    """

    BINDINGS = [("escape", "dismiss", "Close")]

    def __init__(self) -> None:
        super().__init__()
        self._active: str = CATALOG[0].key
        self._router_order: list[str] = []  # selection order == fallback order

    def compose(self) -> ComposeResult:
        with Vertical(id="provider-panel"):
            yield Static("Providers  ·  pick one, or multi-select to build a router", id="provider-title")
            # Scrollable content so a long provider list never pushes the buttons off-screen.
            with VerticalScroll(id="provider-scroll"):
                yield ListView(
                    *[ListItem(Label(_row(e)), id=f"prov-{e.key}") for e in CATALOG],
                    id="prov-list",
                )
                yield Input(placeholder="model override (optional)", id="model-input")
                with Horizontal(id="register-row"):
                    yield Input(placeholder="API key / base_url to register", password=True, id="secret-input")
                    yield Button("Register", id="register-btn")
                yield Static("Router members (space to toggle; order = fallback order):", classes="dim")
                yield SelectionList[str](
                    *[(e.label, e.key) for e in CATALOG], id="router-list",
                )
                yield Static("", id="prov-status", classes="dim")
            # Action buttons stay OUTSIDE the scroll => always visible.
            with Horizontal(id="provider-buttons"):
                yield Button("Use provider", variant="primary", id="use-btn")
                yield Button("Build router", id="router-btn")
                yield Button("＋ Custom (OpenAI-compatible)", id="custom-btn")
                yield Button("Cancel", id="cancel-btn")

    def on_mount(self) -> None:
        self.query_one("#prov-list", ListView).index = 0
        self._sync_secret_placeholder()

    # --- interaction ---

    @on(ListView.Highlighted, "#prov-list")
    def _highlight(self, event: ListView.Highlighted) -> None:
        if event.item and event.item.id:
            self._active = event.item.id.removeprefix("prov-")
            self._sync_secret_placeholder()

    @on(SelectionList.SelectedChanged, "#router-list")
    def _router_changed(self, event: SelectionList.SelectedChanged) -> None:
        selected = set(event.selection_list.selected)
        # Keep prior order for still-selected keys, then append newly selected ones.
        self._router_order = [k for k in self._router_order if k in selected]
        self._router_order += [k for k in selected if k not in self._router_order]

    def _sync_secret_placeholder(self) -> None:
        e = self._entry()
        ph = "base_url (blank = default)" if e.needs_base_url else f"{e.required_env[0]} value"
        self.query_one("#secret-input", Input).placeholder = ph

    def _entry(self) -> ProviderEntry:
        return next(e for e in CATALOG if e.key == self._active)

    @on(Button.Pressed, "#register-btn")
    def _register(self) -> None:
        e = self._entry()
        secret = self.query_one("#secret-input", Input).value.strip()
        model = self.query_one("#model-input", Input).value.strip()
        values: dict[str, str] = {}
        if e.needs_base_url and e.base_url_env:
            values[e.base_url_env] = secret
        elif e.required_env:
            values[e.required_env[0]] = secret
        if model:
            values[e.model_env] = model
        register(e, values)
        self.query_one("#secret-input", Input).value = ""
        self._refresh_rows()
        self.query_one("#prov-status", Static).update(f"Registered {e.label} for this session.")

    def _refresh_rows(self) -> None:
        lst = self.query_one("#prov-list", ListView)
        idx = lst.index
        lst.clear()
        for e in CATALOG:
            lst.append(ListItem(Label(_row(e)), id=f"prov-{e.key}"))
        lst.index = idx

    @on(Button.Pressed, "#use-btn")
    def _use(self) -> None:
        model = self.query_one("#model-input", Input).value.strip()
        self.dismiss({"kind": "provider", "keys": [self._active], "model": model})

    @on(Button.Pressed, "#router-btn")
    def _router(self) -> None:
        if not self._router_order:
            self.query_one("#prov-status", Static).update("Select at least one router member first.")
            return
        self.dismiss({"kind": "router", "keys": list(self._router_order), "model": ""})

    @on(Button.Pressed, "#custom-btn")
    @work
    async def _open_custom(self) -> None:
        # Pass the custom selection straight through; the api_key rides inside it and is
        # never written to env here (build_custom hands it directly to the provider).
        result = await self.app.push_screen_wait(CustomProviderModal())
        if result:
            self.dismiss(result)

    @on(Button.Pressed, "#cancel-btn")
    def _cancel(self) -> None:
        self.dismiss(None)


class CustomProviderModal(ModalScreen[dict]):
    """Bring-your-own OpenAI-compatible provider. Collects name / base_url / model and a
    MASKED api_key, and returns the app's selection dict:
      {"kind": "custom", "params": {"name":…, "base_url":…, "model":…, "api_key":…}}
    or None on cancel.

    # ponytail: the api_key lives ONLY in this in-memory selection — never written to env,
    # never logged, never shown after entry. build_custom passes it straight to the provider
    # (not via os.environ), so no persistence/validation layer is warranted here.
    """

    BINDINGS = [("escape", "cancel", "Cancel")]

    def compose(self) -> ComposeResult:
        with Vertical(id="custom-panel"):
            yield Static("Custom provider (OpenAI-compatible)", id="custom-title")
            yield Static(
                "The API key stays local for this session only — it never reaches the model.",
                classes="dim",
            )
            yield Input(placeholder="name (e.g. my-gateway)", id="custom-name")
            yield Input(placeholder="base_url (e.g. https://host/v1)", id="custom-base-url")
            yield Input(placeholder="model", id="custom-model")
            yield Input(password=True, placeholder="API key (kept local, never logged)",
                        id="custom-api-key")
            with Horizontal(id="custom-buttons"):
                yield Button("Use provider", variant="primary", id="custom-submit-btn")
                yield Button("Cancel", variant="error", id="custom-cancel-btn")

    def on_mount(self) -> None:
        self.query_one("#custom-name", Input).focus()

    @on(Input.Submitted)
    @on(Button.Pressed, "#custom-submit-btn")
    def action_submit(self) -> None:
        params = {
            "name": self.query_one("#custom-name", Input).value.strip(),
            "base_url": self.query_one("#custom-base-url", Input).value.strip(),
            "model": self.query_one("#custom-model", Input).value.strip(),
            "api_key": self.query_one("#custom-api-key", Input).value,  # raw: never stripped/logged
        }
        self.dismiss({"kind": "custom", "params": params})

    @on(Button.Pressed, "#custom-cancel-btn")
    def action_cancel(self) -> None:
        self.dismiss(None)


class ModeScreen(ModalScreen[Mode]):
    """Pick Autonomy + Phase from menus. A reliable alternative to the f2/f3 cycles that
    terminals/multiplexers often swallow. Enter / Set mode returns the chosen Mode; Esc
    cancels. Current values are preselected."""

    BINDINGS = [("escape", "dismiss", "Close")]

    def __init__(self, *, mode: Mode) -> None:
        super().__init__()
        self._mode = mode

    def compose(self) -> ComposeResult:
        with Vertical(id="mode-panel"):
            yield Static("Mode  ·  autonomy + phase", id="mode-title")
            with Horizontal(id="mode-lists"):
                with Vertical(classes="mode-col"):
                    yield Static("Autonomy", classes="cap-section")
                    yield ListView(
                        *[ListItem(Label(a.name.lower()), id=f"aut-{a.name}") for a in Autonomy],
                        id="mode-autonomy",
                    )
                with Vertical(classes="mode-col"):
                    yield Static("Phase", classes="cap-section")
                    yield ListView(
                        *[ListItem(Label(p.name.lower()), id=f"pha-{p.name}") for p in Phase],
                        id="mode-phase",
                    )
            with Horizontal(id="mode-buttons"):
                yield Button("Set mode", variant="primary", id="mode-submit-btn")
                yield Button("Cancel", id="mode-cancel-btn")

    def on_mount(self) -> None:
        self.query_one("#mode-autonomy", ListView).index = list(Autonomy).index(self._mode.autonomy)
        self.query_one("#mode-phase", ListView).index = list(Phase).index(self._mode.phase)

    @on(ListView.Selected)
    @on(Button.Pressed, "#mode-submit-btn")
    def action_submit(self) -> None:
        a = list(Autonomy)[self.query_one("#mode-autonomy", ListView).index or 0]
        p = list(Phase)[self.query_one("#mode-phase", ListView).index or 0]
        self.dismiss(Mode(autonomy=a, phase=p))

    @on(Button.Pressed, "#mode-cancel-btn")
    def action_cancel(self) -> None:
        self.dismiss(None)


class ApprovalModal(ModalScreen[bool]):
    """HITL gate: show the pending tool call and return the operator's Approve/Deny."""

    BINDINGS = [
        ("y", "approve", "Approve"),
        ("n", "deny", "Deny"),
        ("escape", "deny", "Deny"),
    ]

    def __init__(self, *, tool: str, risk: str, target: str | None, reason: str) -> None:
        super().__init__()
        self._tool = tool
        self._risk = risk
        self._target = target
        self._reason = reason

    def compose(self) -> ComposeResult:
        with Vertical(id="approval-panel"):
            yield Static("Authorization required", id="approval-title")
            with VerticalScroll(id="approval-body"):
                yield Label(f"tool    {self._tool}")
                yield Label(f"risk    {self._risk}")
                yield Label(f"target  {self._target or '—'}")
                yield Label(f"reason  {self._reason}")
            with Horizontal(id="approval-buttons"):
                yield Button("Approve", variant="success", id="approve-btn")
                yield Button("Deny", variant="error", id="deny-btn")

    @on(Button.Pressed, "#approve-btn")
    def action_approve(self) -> None:
        self.dismiss(True)

    @on(Button.Pressed, "#deny-btn")
    def action_deny(self) -> None:
        self.dismiss(False)


class SecretModal(ModalScreen[str | None]):
    """Out-of-band secret prompt. The operator pastes a value into a MASKED input; it is
    handed to the Vault via the control plane and NEVER reaches the model. Returns the
    pasted string, or None on cancel (fail-closed => the action is denied)."""

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
    ]

    def __init__(self, *, name: str, reason: str) -> None:
        super().__init__()
        self._name = name
        self._reason = reason

    def compose(self) -> ComposeResult:
        with Vertical(id="secret-panel"):
            yield Static("Secret required", id="secret-title")
            with VerticalScroll(id="secret-body"):
                yield Label(f"name    {self._name}")
                yield Label(f"reason  {self._reason}")
                yield Static(
                    "Stored locally in the vault for this session only — never sent to the model.",
                    classes="dim",
                )
            yield Input(password=True, placeholder=f"paste {self._name}", id="secret-value")
            with Horizontal(id="secret-buttons"):
                yield Button("Submit", variant="primary", id="secret-submit-btn")
                yield Button("Cancel", variant="error", id="secret-cancel-btn")

    def on_mount(self) -> None:
        self.query_one("#secret-value", Input).focus()

    @on(Input.Submitted, "#secret-value")
    @on(Button.Pressed, "#secret-submit-btn")
    def action_submit(self) -> None:
        self.dismiss(self.query_one("#secret-value", Input).value or None)

    @on(Button.Pressed, "#secret-cancel-btn")
    def action_cancel(self) -> None:
        self.dismiss(None)


class CapabilitiesScreen(ModalScreen[None]):
    """Read-only view of what the engine currently has access to: provider/model, tools
    (risk + approval/scope badges), discovered skills, and the NAMES of secrets held.
    Secret values are never read or shown — only vault.names(). Esc to close.

    `engine` may be None (no provider key yet): the static tool catalog is shown instead,
    with an "engine not started" note and no secrets.
    """

    BINDINGS = [
        ("escape", "dismiss", "Close"),
    ]

    def __init__(self, *, engine: Any, provider: str, model: str) -> None:
        super().__init__()
        self._engine = engine
        self._provider = provider
        self._model = model

    def _tools(self) -> dict[str, Any]:
        if self._engine is not None:
            return self._engine.registry._tools
        # ponytail: no engine yet — show the same catalog the engine would build, so the
        # panel is useful before a provider key exists. Import lazily to avoid a cycle.
        from hexharness.engine import default_registry

        return default_registry()._tools

    def _web_backend(self) -> str | None:
        tool = self._tools().get("web_search")
        try:
            return tool.active_backend() if tool is not None else None
        except Exception:  # noqa: BLE001
            return None

    def _secret_names(self) -> list[str]:
        if self._engine is not None and self._engine.vault is not None:
            return self._engine.vault.names()  # NAMES ONLY — never values
        return []

    @staticmethod
    def _skills() -> list[Any]:
        if not _SKILLS_LIBRARY.is_dir():
            return []
        from hexharness.skills.engine import SkillRegistry

        return SkillRegistry().discover(_SKILLS_LIBRARY).list_metadata()

    def compose(self) -> ComposeResult:
        with Vertical(id="capabilities-panel"):
            yield Static("Capabilities", id="capabilities-title")
            with VerticalScroll(id="capabilities-body"):
                if self._engine is None:
                    yield Static("engine not started — showing the static catalog", classes="dim")

                yield Static("Provider / model", classes="cap-section")
                yield Label(f"  {self._provider}/{self._model}")

                yield Static("Tools", classes="cap-section")
                for tool in self._tools().values():
                    flags = []
                    if getattr(tool, "requires_approval", False):
                        flags.append("● requires approval")
                    if getattr(tool, "scope_sensitive", False):
                        flags.append("scope")
                    suffix = f"  —  {', '.join(flags)}" if flags else ""
                    yield Label(f"  {tool.name}  ·  {tool.risk_level.name.lower()}{suffix}")
                yield Static("  MCP tools appear here once connected.", classes="dim")

                backend = self._web_backend()
                if backend:
                    yield Static("Web search", classes="cap-section")
                    yield Label(f"  active backend: {backend}"
                                + ("  (free, no key)" if backend == "duckduckgo" else "  (via API key)"))

                yield Static("Skills available", classes="cap-section")
                skills = self._skills()
                if skills:
                    for s in skills:
                        yield Label(f"  {s.name}  ({s.phase})  —  {s.description}")
                else:
                    yield Label("  (none discovered)")

                yield Static("Secrets held (names only)", classes="cap-section")
                names = self._secret_names()
                if names:
                    for name in names:
                        yield Label(f"  {name}")
                else:
                    yield Label("  (none)")


class FindingsScreen(ModalScreen[None]):
    """Findings panel — invariant #5: the agent only ever records CANDIDATEs; a human
    promotes them. Lists findings grouped CANDIDATES / CONFIRMED / REJECTED, and lets the
    operator Confirm or Reject the highlighted candidate (keys `c` / `r`, or the buttons).
    Curation goes through the EvidenceStore (`confirm`/`reject`), which emits the audit
    event and moves the finding out of candidates; the lists then re-query in place.

    `engine` may be None (no run yet => no evidence store): an empty-state note is shown.
    Esc closes.
    """

    BINDINGS = [
        ("escape", "dismiss", "Close"),
        ("c", "confirm", "Confirm"),
        ("r", "reject", "Reject"),
    ]

    def __init__(self, *, engine: Any) -> None:
        super().__init__()
        self._engine = engine
        self._active: str | None = None  # highlighted candidate's finding id

    # --- data (re-queries the store every call, so refresh == rebuild from source) ---

    def _groups(self) -> tuple[list[Any], list[Any], list[Any]]:
        """(candidates, confirmed, rejected) straight from the store; () if no engine."""
        if self._engine is None:
            return ([], [], [])
        ev = self._engine.evidence
        return (ev.candidates(), ev.confirmed(), ev.rejected())

    def _title(self) -> str:
        c, cf, rj = (len(g) for g in self._groups())
        return f"Findings · {c} candidate · {cf} confirmed · {rj} rejected"

    @staticmethod
    def _row(f: Any, *, hint: bool = False) -> str:
        base = f"  {f.severity.value:8} {f.title}  —  {f.target or '—'}"
        return base + "   [c confirm · r reject]" if hint else base

    # --- layout ---

    def compose(self) -> ComposeResult:
        with Vertical(id="findings-panel"):
            yield Static(self._title(), id="findings-title")
            if self._engine is None:
                yield Static(
                    "no engagement running yet — findings appear once the agent records them",
                    classes="dim",
                )
                return
            # Content scrolls; action buttons stay OUTSIDE the scroll => always visible.
            with VerticalScroll(id="findings-scroll"):
                yield Static("Candidates  (c confirm · r reject)", classes="cap-section")
                yield ListView(id="cand-list")
                yield Static("Confirmed", classes="cap-section")
                yield Vertical(id="confirmed-box")
                yield Static("Rejected", classes="cap-section")
                yield Vertical(id="rejected-box")
            with Horizontal(id="findings-buttons"):
                yield Button("Confirm", variant="success", id="confirm-btn")
                yield Button("Reject", variant="error", id="reject-btn")
                yield Button("Close", id="close-btn")

    async def on_mount(self) -> None:
        if self._engine is not None:
            await self._rebuild()

    async def _rebuild(self) -> None:
        cands, conf, rej = self._groups()
        self.query_one("#findings-title", Static).update(self._title())
        lst = self.query_one("#cand-list", ListView)
        await lst.clear()
        for f in cands:
            await lst.append(ListItem(Label(self._row(f, hint=True)), id=f"cand-{f.id}"))
        self._active = cands[0].id if cands else None
        if cands:
            lst.index = 0
        await self._fill("#confirmed-box", conf)
        await self._fill("#rejected-box", rej)

    async def _fill(self, selector: str, findings: list[Any]) -> None:
        box = self.query_one(selector, Vertical)
        await box.remove_children()
        if findings:
            for f in findings:
                await box.mount(Label(self._row(f)))
        else:
            await box.mount(Label("  (none)", classes="dim"))

    # --- interaction ---

    @on(ListView.Highlighted, "#cand-list")
    def _highlight(self, event: ListView.Highlighted) -> None:
        self._active = event.item.id.removeprefix("cand-") if event.item and event.item.id else None

    def action_confirm(self) -> None:
        self._curate("confirm")

    def action_reject(self) -> None:
        self._curate("reject")

    @on(Button.Pressed, "#confirm-btn")
    def _confirm_btn(self) -> None:
        self._curate("confirm")

    @on(Button.Pressed, "#reject-btn")
    def _reject_btn(self) -> None:
        self._curate("reject")

    @on(Button.Pressed, "#close-btn")
    def _close_btn(self) -> None:
        self.dismiss(None)

    @work
    async def _curate(self, action: str) -> None:
        fid = self._active
        if fid is None:
            return
        if action == "confirm":
            await self.confirm_finding(fid)
        else:
            await self.reject_finding(fid)
        await self._rebuild()  # finding moved out of candidates => re-read in place

    # Store calls split out from the UI refresh so they're drivable without a mounted tree.
    async def confirm_finding(self, fid: str) -> None:
        await self._engine.evidence.confirm(fid, curator="operator")

    async def reject_finding(self, fid: str) -> None:
        await self._engine.evidence.reject(fid, curator="operator", reason="rejected via TUI")
