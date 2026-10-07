"""Modal screens: provider selection / registration, the HITL approval prompt, the
masked secret-input prompt, and a read-only capabilities panel."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from textual import on, work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, ListItem, ListView, Select, SelectionList, Static

from hexharness.control.policy import Autonomy, Mode, Phase
from hexharness.tui.providers import ProviderEntry, all_entries, detect, model_for, register

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
        # Catalog + saved custom providers; snapshot once so the list is stable for the
        # screen's lifetime (registering a key only flips badges, never the membership).
        self._entries: list[ProviderEntry] = all_entries()
        # Widget IDs can't contain ":" (custom keys look like "custom:mygw"), so map a
        # DOM-safe id back to the real provider key.
        self._id_to_key: dict[str, str] = {self._key_id(e): e.key for e in self._entries}
        self._active: str = self._entries[0].key
        self._router_order: list[str] = []  # selection order == fallback order

    @staticmethod
    def _key_id(e: ProviderEntry) -> str:
        return e.key.replace(":", "_")

    def compose(self) -> ComposeResult:
        with Vertical(id="provider-panel"):
            yield Static("Providers  ·  pick one, or multi-select to build a router", id="provider-title")
            # Scrollable content so a long provider list never pushes the buttons off-screen.
            with VerticalScroll(id="provider-scroll"):
                yield ListView(
                    *[ListItem(Label(_row(e)), id=f"prov-{self._key_id(e)}") for e in self._entries],
                    id="prov-list",
                )
                yield Input(placeholder="model override (optional)", id="model-input")
                with Horizontal(id="register-row"):
                    yield Input(placeholder="API key / base_url to register", password=True, id="secret-input")
                    yield Button("Register", id="register-btn")
                yield Static("Router members (space to toggle; order = fallback order):", classes="dim")
                yield SelectionList[str](
                    *[(e.label, e.key) for e in self._entries], id="router-list",
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
            self._active = self._id_to_key.get(event.item.id.removeprefix("prov-"), self._active)
            self._sync_secret_placeholder()

    @on(SelectionList.SelectedChanged, "#router-list")
    def _router_changed(self, event: SelectionList.SelectedChanged) -> None:
        selected = set(event.selection_list.selected)
        # Keep prior order for still-selected keys, then append newly selected ones.
        self._router_order = [k for k in self._router_order if k in selected]
        self._router_order += [k for k in selected if k not in self._router_order]

    def _sync_secret_placeholder(self) -> None:
        e = self._entry()
        if e.needs_base_url:
            ph = "base_url (blank = default)"
        elif e.required_env:
            ph = f"{e.required_env[0]} value"
        else:
            ph = "saved custom — key already stored"
        self.query_one("#secret-input", Input).placeholder = ph

    def _entry(self) -> ProviderEntry:
        return next(e for e in self._entries if e.key == self._active)

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
        for e in self._entries:
            lst.append(ListItem(Label(_row(e)), id=f"prov-{self._key_id(e)}"))
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


# ROE ceiling choices, shared by the Mode screen (Ctrl+O) and the scope editor (Ctrl+E).
ROE_CHOICES = {
    "max_risk": ("passive", "active", "intrusive", "destructive"),
    "max_autonomy": ("plan", "report", "interactive", "auto", "bypass"),
    "max_phase": ("recon", "enumeration", "exploitation", "post_exploitation", "reporting", "bypass"),
}


class ModeScreen(ModalScreen[dict]):
    """Pick Autonomy + Phase from menus. A reliable alternative to the f2/f3 cycles that
    terminals/multiplexers often swallow. Enter / Set mode returns the chosen Mode; Esc
    cancels. Current values are preselected."""

    BINDINGS = [("escape", "dismiss", "Close")]

    def __init__(self, *, mode: Mode, roe: dict | None = None) -> None:
        super().__init__()
        self._mode = mode
        self._roe = roe or {"max_risk": "active", "max_autonomy": "interactive", "max_phase": "enumeration"}

    def compose(self) -> ComposeResult:
        with Vertical(id="mode-panel"):
            yield Static("Mode  ·  autonomy + phase  ·  ROE ceiling", id="mode-title")
            with VerticalScroll(id="mode-body"):
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
                yield Static("ROE ceiling (the hard cap — the mode above is clamped to this)",
                             classes="cap-section")
                for field, choices in ROE_CHOICES.items():
                    yield Label(f"  {field}")
                    yield Select([(c, c) for c in choices], value=self._roe[field],
                                 allow_blank=False, id=f"mode-roe-{field.replace('_', '-')}")
            with Horizontal(id="mode-buttons"):
                yield Button("Apply", variant="primary", id="mode-submit-btn")
                yield Button("Cancel", id="mode-cancel-btn")

    def on_mount(self) -> None:
        self.query_one("#mode-autonomy", ListView).index = list(Autonomy).index(self._mode.autonomy)
        self.query_one("#mode-phase", ListView).index = list(Phase).index(self._mode.phase)

    @on(Button.Pressed, "#mode-submit-btn")
    def action_submit(self) -> None:
        a = list(Autonomy)[self.query_one("#mode-autonomy", ListView).index or 0]
        p = list(Phase)[self.query_one("#mode-phase", ListView).index or 0]
        roe = {f: self.query_one(f"#mode-roe-{f.replace('_', '-')}", Select).value for f in ROE_CHOICES}
        self.dismiss({"mode": Mode(autonomy=a, phase=p), "roe": roe})

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


class ScopeApprovalModal(ModalScreen[bool]):
    """Human gate for a runtime scope/ROE change the model proposed. Dismisses True to
    apply, False to reject. This modal is the ONLY path to activation, so no mode (not
    even bypass) can skip it."""

    BINDINGS = [("escape", "dismiss", "Reject"), ("y", "ok", "Approve"), ("n", "dismiss", "Reject")]

    def __init__(self, engagement: Any) -> None:
        super().__init__()
        self._eng = engagement

    def compose(self) -> ComposeResult:
        e = self._eng
        with Vertical(id="scope-panel"):
            yield Static("Approve scope change?", id="scope-title")
            yield Static("The model proposed a new engagement. It activates only if you approve.",
                         classes="dim")
            with VerticalScroll(id="scope-body"):
                yield Label(f"Engagement: {e.name}" + (f"  (client: {e.client})" if e.client else ""))
                yield Static("Scope", classes="cap-section")
                for d in e.scope.domains:
                    yield Label(f"  domain: {d}")
                for c in e.scope.cidrs:
                    yield Label(f"  cidr: {c}")
                for x in e.scope.exclusions:
                    yield Label(f"  exclude: {x}")
                yield Static("ROE", classes="cap-section")
                yield Label(f"  max_risk: {e.roe.max_risk}  ·  max_autonomy: {e.roe.max_autonomy}"
                            f"  ·  max_phase: {e.roe.max_phase}")
            with Horizontal(id="scope-buttons"):
                yield Button("Approve & apply", variant="primary", id="scope-ok")
                yield Button("Reject", id="scope-no")

    @on(Button.Pressed, "#scope-ok")
    def _ok(self) -> None:
        self.dismiss(True)

    @on(Button.Pressed, "#scope-no")
    def _no(self) -> None:
        self.dismiss(False)

    def action_ok(self) -> None:
        self.dismiss(True)


class EngagementEditScreen(ModalScreen[dict]):
    """Full engagement editor: the operator edits EVERY engagement setting directly
    (name, client, scope, ROE ceiling + time windows, budget, report template) and applies
    it WITHOUT involving the model. This dialog IS the human action, so it needs no extra
    approval gate. Dismisses on Apply with a COMPLETE engagement-data dict ready for
    `Engagement.model_validate(...)` — the passed engagement's `.model_dump()` with the
    edited fields overlaid — or None on Cancel/Esc. Field validity (bad CIDR, bad number,
    bad time window) is checked by the apply path, not here."""

    BINDINGS = [("escape", "dismiss", "Cancel")]

    # (scope key, row prefix, add-input placeholder)
    _GROUPS = (
        ("domains", "domain", "add a domain (e.g. app.example)"),
        ("cidrs", "cidr", "add a CIDR (e.g. 10.0.0.0/24)"),
        ("exclusions", "exclude", "add an exclusion (domain or CIDR)"),
    )
    _PREFIX = {k: p for k, p, _ in _GROUPS}

    def __init__(self, *, engagement: Any) -> None:
        super().__init__()
        # Full snapshot — apply overlays the edited fields onto this and dismisses it whole.
        self._data = engagement.model_dump()
        self._name = engagement.name
        # Working copies — edits never touch the source engagement until the app applies.
        self._scope = {
            "domains": list(engagement.scope.domains),
            "cidrs": list(engagement.scope.cidrs),
            "exclusions": list(engagement.scope.exclusions),
        }
        self._roe = {
            "max_risk": engagement.roe.max_risk,
            "max_autonomy": engagement.roe.max_autonomy,
            "max_phase": engagement.roe.max_phase,
        }
        self._windows = [{"start": w.start, "end": w.end} for w in engagement.roe.windows]

    _ROE_CHOICES = ROE_CHOICES  # shared with the Mode screen

    @staticmethod
    def _as_str(value: Any) -> str:
        return "" if value is None else str(value)

    def compose(self) -> ComposeResult:
        b = self._data["budget"]
        with Vertical(id="scope-edit-panel"):
            yield Static(f"Edit engagement · {self._name}", id="scope-edit-title")
            yield Static("Edit the engagement directly, then Apply. The model is not involved.",
                         classes="dim")
            with VerticalScroll(id="scope-edit-body"):
                yield Static("Identity", classes="cap-section")
                yield Input(value=self._name, placeholder="engagement name", id="eng-name")
                yield Input(value=self._data["client"], placeholder="client", id="eng-client")

                yield Static("Scope", classes="cap-section")
                for key, _prefix, placeholder in self._GROUPS:
                    with Horizontal(classes="scope-add-row"):
                        yield Input(placeholder=placeholder, id=f"add-{key}")
                        yield Button("Add", id=f"add-{key}-btn")
                yield ListView(id="scope-entries")
                yield Button("Remove selected", id="scope-remove-btn")

                yield Static("ROE ceiling (the hard cap — raise it to allow riskier tools)",
                             classes="cap-section")
                for field, choices in self._ROE_CHOICES.items():
                    yield Label(f"  {field}")
                    yield Select([(c, c) for c in choices], value=self._roe[field],
                                 allow_blank=False, id=f"roe-{field.replace('_', '-')}")

                yield Static("Time windows (HH:MM — empty list = anytime)", classes="cap-section")
                with Horizontal(classes="scope-add-row"):
                    yield Input(placeholder="start (e.g. 09:00)", id="win-start")
                    yield Input(placeholder="end (e.g. 18:00)", id="win-end")
                    yield Button("Add", id="window-add-btn")
                yield ListView(id="window-entries")
                yield Button("Remove selected", id="window-remove-btn")

                yield Static("Budget (empty = unlimited)", classes="cap-section")
                yield Label("  max_tokens")
                yield Input(value=self._as_str(b["max_tokens"]), placeholder="unlimited", id="bud-tokens")
                yield Label("  max_usd")
                yield Input(value=self._as_str(b["max_usd"]), placeholder="unlimited", id="bud-usd")
                yield Label("  max_seconds")
                yield Input(value=self._as_str(b["max_seconds"]), placeholder="unlimited", id="bud-seconds")

                yield Static("Report", classes="cap-section")
                yield Input(value=self._data["report_template"], placeholder="report template",
                            id="eng-report")
            with Horizontal(id="scope-edit-buttons"):
                yield Button("Apply", variant="primary", id="scope-apply-btn")
                yield Button("Cancel", id="scope-edit-cancel-btn")

    async def on_mount(self) -> None:
        await self._refresh()
        await self._refresh_windows()

    # --- the combined scope entry list (domain/cidr/exclude rows in group order) ---

    def _entries(self) -> list[tuple[str, str]]:
        return [(key, v) for key, _p, _ph in self._GROUPS for v in self._scope[key]]

    async def _refresh(self) -> None:
        lst = self.query_one("#scope-entries", ListView)
        await lst.clear()  # async: await before re-adding or the old items collide
        # No per-item id — removal is by highlighted index, and ids would clash on re-add.
        for key, value in self._entries():
            lst.append(ListItem(Label(f"{self._PREFIX[key]}: {value}")))

    async def _add(self, key: str) -> None:
        inp = self.query_one(f"#add-{key}", Input)
        value = inp.value.strip()
        if value and value not in self._scope[key]:
            self._scope[key].append(value)
        inp.value = ""
        await self._refresh()

    async def _remove_selected(self) -> None:
        idx = self.query_one("#scope-entries", ListView).index
        entries = self._entries()
        if idx is None or not 0 <= idx < len(entries):
            return
        key, value = entries[idx]
        self._scope[key].remove(value)
        await self._refresh()

    # --- time windows (same async-safe add/remove-by-index pattern as scope) ---

    async def _refresh_windows(self) -> None:
        lst = self.query_one("#window-entries", ListView)
        await lst.clear()
        for w in self._windows:
            lst.append(ListItem(Label(f"{w['start']} – {w['end']}")))

    async def _add_window(self) -> None:
        start = self.query_one("#win-start", Input).value.strip()
        end = self.query_one("#win-end", Input).value.strip()
        if start and end:
            self._windows.append({"start": start, "end": end})
            self.query_one("#win-start", Input).value = ""
            self.query_one("#win-end", Input).value = ""
        await self._refresh_windows()

    async def _remove_window(self) -> None:
        idx = self.query_one("#window-entries", ListView).index
        if idx is None or not 0 <= idx < len(self._windows):
            return
        del self._windows[idx]
        await self._refresh_windows()

    # --- apply: overlay the edited fields onto the full snapshot and dismiss it whole ---

    def _budget_val(self, selector: str) -> Any:
        # ponytail: empty -> None (unlimited); otherwise pass the raw string straight to
        # pydantic, which coerces int/float and raises on a bad number at the apply path.
        raw = self.query_one(selector, Input).value.strip()
        return raw or None

    def _apply(self) -> None:
        data = dict(self._data)
        data["name"] = self.query_one("#eng-name", Input).value.strip()
        data["client"] = self.query_one("#eng-client", Input).value.strip()
        data["scope"] = self._scope
        roe = dict(self._data["roe"])
        for f in self._ROE_CHOICES:
            roe[f] = self.query_one(f"#roe-{f.replace('_', '-')}", Select).value
        roe["windows"] = list(self._windows)
        data["roe"] = roe
        data["budget"] = {
            "max_tokens": self._budget_val("#bud-tokens"),
            "max_usd": self._budget_val("#bud-usd"),
            "max_seconds": self._budget_val("#bud-seconds"),
        }
        data["report_template"] = self.query_one("#eng-report", Input).value.strip()
        self.dismiss(data)

    # --- interaction (one dispatcher keeps the per-button @on handlers from double-firing) ---

    @on(Input.Submitted)
    async def _input_submitted(self, event: Input.Submitted) -> None:
        bid = event.input.id or ""
        if bid in ("win-start", "win-end"):
            await self._add_window()
        elif bid.startswith("add-"):
            await self._add(bid.removeprefix("add-"))

    @on(Button.Pressed)
    async def _pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id or ""
        if bid == "scope-apply-btn":
            self._apply()
        elif bid == "scope-edit-cancel-btn":
            self.dismiss(None)
        elif bid == "scope-remove-btn":
            await self._remove_selected()
        elif bid == "window-add-btn":
            await self._add_window()
        elif bid == "window-remove-btn":
            await self._remove_window()
        elif bid.startswith("add-") and bid.endswith("-btn"):
            await self._add(bid.removeprefix("add-").removesuffix("-btn"))
