"""HexTUI — an OpenCode-styled Textual front-end for the HexHarness engine.

Layout: a one-line header, a big scrolling transcript, a bordered prompt input, and a
footer of keybinds. Submitting the prompt runs the agent loop in a worker while a bus
subscriber streams colored control-plane events into the transcript live.
"""
from __future__ import annotations

from pathlib import Path

from rich.text import Text
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Footer, RichLog, Static

from hexharness.control.policy import Autonomy, Mode, Phase
from hexharness.engine import Engine
from hexharness.events.types import Event, EventType
from hexharness.tui.approver import TUIApprover, TUISecretRequester
from hexharness.tui.widgets import PromptArea
from hexharness.tui import providers
from hexharness.tui.providers import build, entry, model_for, router_spec
from hexharness.tui.screens import CapabilitiesScreen, ModeScreen, ProviderScreen

DEFAULT_ENGAGEMENT = "engagements/example.engagement.yaml"

# Mirrors styles.tcss so transcript lines match the theme.
_ACCENT = "#d9894f"
_SUCCESS = "#7fb069"
_DANGER = "#d9534f"
_WARNING = "#e0b54a"
_MUTED = "#6e6e7e"
_TEXT = "#c8c8d0"


class HexHeader(Static):
    """One-line status bar: engagement · provider/model · autonomy/phase · budget."""


class HexTUI(App):
    CSS_PATH = "styles.tcss"
    TITLE = "HexHarness"
    ENABLE_COMMAND_PALETTE = False  # free ctrl+p for the provider screen

    BINDINGS = [
        Binding("ctrl+p", "providers", "Providers"),
        Binding("ctrl+t", "capabilities", "Capabilities"),
        Binding("ctrl+k", "kill", "Kill switch"),
        Binding("ctrl+l", "clear", "Clear"),
        Binding("ctrl+o", "mode", "Mode"),
        Binding("ctrl+r", "dictate", "Dictate"),
        Binding("f2", "cycle_autonomy", "Autonomy", show=False),  # fallback for ctrl+o
        Binding("f3", "cycle_phase", "Phase", show=False),        # fallback for ctrl+o
        Binding("ctrl+q", "quit", "Quit"),
        Binding("ctrl+c", "quit", "Quit", show=False),
    ]

    def __init__(self, *, engagement: str | Path = DEFAULT_ENGAGEMENT) -> None:
        super().__init__()
        self.engagement_path = str(engagement)
        self.mode = Mode(autonomy=Autonomy.INTERACTIVE, phase=Phase.RECON)
        self.engine: Engine | None = None
        self.loop = None
        self._selection = {"kind": "provider", "keys": ["anthropic"], "model": ""}
        self._tokens = 0
        self._usd = 0.0
        self._live_buf = ""       # accumulating streamed text for the current model turn
        self._streamed = False    # did any text stream this run? (non-streaming providers: no)
        self._dictation = None    # lazy push-to-talk dictation (local Whisper)
        self._dict_base = ""      # prompt text present when dictation started

    # --- layout ---

    def compose(self) -> ComposeResult:
        yield HexHeader(id="header")
        yield RichLog(id="transcript", wrap=True, markup=False, highlight=False)
        yield Static("", id="live")  # live-streaming model text for the current turn
        # multi-line, soft-wrapping, auto-growing prompt (Enter submits, Ctrl+J newline)
        yield PromptArea(id="prompt", soft_wrap=True)
        yield Footer()

    def on_mount(self) -> None:
        self._sync_header()
        self.query_one("#prompt", PromptArea).focus()
        self._log("HexHarness ready. Ctrl+P to pick a provider, then type a task.", _MUTED)

    # --- header ---

    def _provider_model(self) -> tuple[str, str]:
        if self._selection["kind"] == "router":
            return "router(" + "+".join(self._selection["keys"]) + ")", "auto"
        if self._selection["kind"] == "custom":
            p = self._selection["params"]
            return p["name"] or "custom", p["model"]
        e = entry(self._selection["keys"][0])
        return e.key, (self._selection.get("model") or model_for(e))

    def _sync_header(self) -> None:
        eng = self.engine.engagement.name if self.engine else Path(self.engagement_path).stem
        provider, model = self._provider_model()
        parts = [
            "HexHarness",
            eng,
            f"{provider}/{model}",
            f"{self.mode.autonomy.name.lower()}/{self.mode.phase.name.lower()}",
        ]
        if self._tokens or self._usd:
            parts.append(f"{self._tokens:,} tok  ${self._usd:.4f}")
        self.query_one("#header", HexHeader).update("  ·  ".join(parts))

    # --- transcript ---

    def _log(self, text: str, style: str = _TEXT) -> None:
        self.query_one("#transcript", RichLog).write(Text(text, style=style))

    def _model_override(self) -> str | None:
        if self._selection["kind"] == "router":
            return None
        if self._selection["kind"] == "custom":
            return self._selection["params"].get("model") or None
        return self._selection.get("model") or None

    # --- engine lifecycle ---

    def _make_provider(self):
        if self._selection["kind"] == "router":
            return router_spec([entry(k) for k in self._selection["keys"]])
        if self._selection["kind"] == "custom":
            # ponytail: api_key is passed straight through from the in-memory selection,
            # never via os.environ — build_custom hands it directly to the provider.
            return providers.build_custom(**self._selection["params"])
        e = entry(self._selection["keys"][0])
        return build(e, model=self._selection.get("model") or None)

    def _ensure_engine(self) -> None:
        if self.engine is not None:
            return
        provider = self._make_provider()  # may raise RuntimeError if a key is missing
        self.engine = Engine.from_engagement(
            self.engagement_path, provider=provider, requested_mode=self.mode,
            approver=TUIApprover(self), secret_requester=TUISecretRequester(self),
        )
        self.engine.events._bus.subscribe(self._on_event)
        self.loop = self.engine.loop(provider=provider, model=self._model_override(),
                                     on_text=self._stream_text)
        self._sync_header()

    def _stream_text(self, delta: str) -> None:
        """Token sink (runs on the app loop). Grow the live line; it's flushed into the
        transcript permanently when the turn's MODEL_RESPONSE event arrives."""
        self._streamed = True
        self._live_buf += delta
        self.query_one("#live", Static).update(Text(self._live_buf, style=_TEXT))

    def _flush_live(self) -> None:
        if self._live_buf:
            self._log(self._live_buf, _TEXT)
            self._live_buf = ""
            self.query_one("#live", Static).update("")

    # --- running ---

    @on(PromptArea.Submitted)
    def _submit(self, event: PromptArea.Submitted) -> None:
        prompt = event.text.strip()
        if not prompt:
            return
        self.query_one("#prompt", PromptArea).text = ""
        self._run(prompt)

    @work(exclusive=True)
    async def _run(self, prompt: str) -> None:
        box = self.query_one("#prompt", PromptArea)
        box.disabled = True
        self._log(f"❯ {prompt}", _ACCENT)
        self._live_buf = ""
        self._streamed = False
        try:
            self._ensure_engine()
            result = await self.loop.run(prompt)
            self._flush_live()
            # Streaming already showed every turn's text; only write the return value
            # when nothing streamed (e.g. a provider that doesn't support on_text yet).
            if not self._streamed:
                self._log(result or "(no output)", _TEXT)
        except RuntimeError as exc:
            # Most likely a missing API key — point the operator at the provider screen.
            self._log(f"provider error: {exc}  (Ctrl+P to configure)", _DANGER)
            self.engine = None
        except Exception as exc:  # noqa: BLE001 — surface, never crash the UI
            self._log(f"error: {exc}", _DANGER)
        finally:
            box.disabled = False
            box.focus()

    def _on_event(self, event: Event) -> None:
        """Bus subscriber — runs on the app loop, so writing widgets here is safe."""
        p = event.payload
        t = event.type
        if t is EventType.AUTHORIZE_DECISION:
            effect = str(p.get("effect", "")).lower()
            style = {"allow": _SUCCESS, "deny": _DANGER, "ask": _WARNING}.get(effect, _TEXT)
            tgt = f" {p.get('target')}" if p.get("target") else ""
            self._log(f"{effect.upper():5} {p.get('tool')} ({p.get('risk')}){tgt} — "
                      f"{p.get('gate')}: {p.get('reason')}", style)
        elif t is EventType.TOOL_STARTED:
            self._log(f"→ {p.get('tool')} {p.get('input', {})}", _MUTED)
        elif t is EventType.TOOL_FINISHED:
            mark = "✓" if p.get("ok") else "✗"
            extra = "" if p.get("ok") else f" — {p.get('error', '')}"
            self._log(f"{mark} {p.get('tool')}{extra}", _MUTED)
        elif t is EventType.MODEL_RESPONSE:
            self._flush_live()  # streamed text for this turn becomes a permanent line
            self._log(f"· model ({p.get('tokens', 0)} tok, {p.get('stop_reason')})", _MUTED)
        elif t is EventType.FINDING_CANDIDATE:
            self._log(f"finding candidate: {p}", _WARNING)
        elif t is EventType.FINDING_CONFIRMED:
            self._log(f"finding confirmed: {p}", _SUCCESS)
        elif t is EventType.FINDING_REJECTED:
            self._log(f"finding rejected: {p}", _MUTED)
        elif t is EventType.BUDGET_UPDATED:
            self._tokens = p.get("tokens_used", self._tokens)
            self._usd = p.get("usd_used", self._usd)
            self._sync_header()
        elif t is EventType.KILL_REQUESTED:
            self._log(f"KILL requested: {p.get('reason', '')}", _DANGER)
        elif t in (EventType.DELEGATION_STARTED, EventType.DELEGATION_FINISHED):
            self._log(f"{t.name.lower()}: {p}", _MUTED)
        elif t is EventType.CHECKPOINT:
            self._log(f"checkpoint: {p.get('reason', '')}", _MUTED)

    # --- actions ---

    @work
    async def action_providers(self) -> None:
        result = await self.push_screen_wait(ProviderScreen())
        if not result:
            return
        self._selection = result
        self.engine = None  # rebuild with the new provider on the next run
        self.loop = None
        self._sync_header()
        self._log(f"provider set: {self._provider_model()[0]}", _MUTED)

    @work
    async def action_mode(self) -> None:
        result = await self.push_screen_wait(ModeScreen(mode=self.mode))
        if result is None:
            return
        self.mode = result
        self._reset_mode()  # drop the engine so the next run rebuilds with the new mode
        self._log(f"mode set: {self.mode.autonomy.name.lower()}/{self.mode.phase.name.lower()}", _MUTED)

    @work(exclusive=True, group="dictate")
    async def action_dictate(self) -> None:
        """Toggle push-to-talk dictation. Transcribes locally (Whisper) — audio never
        leaves the machine. Ctrl+R starts; Ctrl+R again stops and inserts the text."""
        from hexharness.voice.dictation import Dictation

        if not Dictation.available():
            self._log("voice not available — pip install -e '.[voice]'", _WARNING)
            return
        if self._dictation is None:
            self._dictation = Dictation()

        box = self.query_one("#prompt", PromptArea)
        if not self._dictation.is_recording:
            # Remember whatever was already typed; dictation appends to it, live.
            self._dict_base = box.text.strip()
            self._dictation.start(on_partial=self._dictation_partial)
            self._log("● recording… speak; prompt fills live (Ctrl+R to stop)", _DANGER)
            return

        text = (await self._dictation.stop_and_transcribe()).strip()
        box.text = f"{self._dict_base} {text}".strip() if self._dict_base else text
        box.focus()
        self._log("🎙 done" if text else "(no speech detected)", _MUTED)

    def _dictation_partial(self, text: str) -> None:
        """Live partial transcript -> prompt, as the operator speaks (app loop)."""
        box = self.query_one("#prompt", PromptArea)
        box.text = f"{self._dict_base} {text}".strip() if self._dict_base else text

    @work
    async def action_capabilities(self) -> None:
        # Build the engine so the panel reflects the live registry/vault; fall back to the
        # static catalog if no provider key is configured yet (never crash the UI).
        try:
            self._ensure_engine()
        except RuntimeError:
            pass
        provider, model = self._provider_model()
        await self.push_screen_wait(
            CapabilitiesScreen(engine=self.engine, provider=provider, model=model)
        )

    async def action_kill(self) -> None:
        if self.engine is None:
            self._log("kill switch: no engine running", _MUTED)
            return
        await self.engine.kill_switch.trigger("tui kill switch")
        self._log("kill switch triggered — run will stop at its next boundary", _DANGER)

    def action_clear(self) -> None:
        self.query_one("#transcript", RichLog).clear()

    def action_cycle_autonomy(self) -> None:
        members = list(Autonomy)
        nxt = members[(members.index(self.mode.autonomy) + 1) % len(members)]
        self.mode = Mode(autonomy=nxt, phase=self.mode.phase)
        self._reset_mode()

    def action_cycle_phase(self) -> None:
        members = list(Phase)
        nxt = members[(members.index(self.mode.phase) + 1) % len(members)]
        self.mode = Mode(autonomy=self.mode.autonomy, phase=nxt)
        self._reset_mode()

    def _reset_mode(self) -> None:
        # Mode is baked into ExecContext at assembly, so drop the engine to apply it next run.
        self.engine = None
        self.loop = None
        self._sync_header()
