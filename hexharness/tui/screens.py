"""Modal screens: provider selection / registration, and the HITL approval prompt."""
from __future__ import annotations

from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, ListItem, ListView, SelectionList, Static

from hexharness.tui.providers import CATALOG, ProviderEntry, detect, model_for, register


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
