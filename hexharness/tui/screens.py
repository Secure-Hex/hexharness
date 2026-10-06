"""Modal screens: provider selection / registration, the HITL approval prompt, the
masked secret-input prompt, and a read-only capabilities panel."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, ListItem, ListView, SelectionList, Static

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
            with Horizontal(id="provider-buttons"):
                yield Button("Use provider", variant="primary", id="use-btn")
                yield Button("Build router", id="router-btn")
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

    @on(Button.Pressed, "#cancel-btn")
    def _cancel(self) -> None:
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
