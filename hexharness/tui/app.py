"""HexTUI — an OpenCode-styled Textual front-end for the HexHarness engine.

Layout: a one-line header, a big scrolling transcript, a bordered prompt input, and a
footer of keybinds. Submitting the prompt runs the agent loop in a worker while a bus
subscriber streams colored control-plane events into the transcript live.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

from rich.markdown import Markdown
from rich.text import Text
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Footer, RichLog, Static

from hexharness.agent.context import ExecContext
from hexharness.control.policy import Autonomy, Mode, Phase
from hexharness.engine import Engine
from hexharness.events.types import Event, EventType
from hexharness.skills.slash import expand_slash, is_list_request, list_skills
from hexharness.tui.approver import TUIApprover, TUISecretRequester
from hexharness.tui.widgets import PromptArea
from hexharness.tui import providers
from hexharness.tui.providers import build, entry, model_for, router_spec
from hexharness.tui.screens import (
    CapabilitiesScreen,
    EngagementEditScreen,
    FindingsScreen,
    ModeScreen,
    ProviderScreen,
    ScopeApprovalModal,
)

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

    # The full keybind list lives in the toggleable Commands side panel (Ctrl+B); the
    # footer stays uncluttered — only the toggle is shown there (show=False elsewhere).
    BINDINGS = [
        Binding("ctrl+b", "commands", "Commands", priority=True),
        Binding("ctrl+p", "providers", "Providers", show=False),
        Binding("ctrl+t", "capabilities", "Capabilities", show=False),
        Binding("ctrl+f", "findings", "Findings", show=False),
        Binding("ctrl+k", "kill", "Kill switch", show=False),
        Binding("ctrl+l", "clear", "Clear", show=False),
        Binding("ctrl+o", "mode", "Mode", show=False),
        Binding("ctrl+e", "edit_scope", "Edit engagement", priority=True, show=False),  # TextArea also uses ctrl+e
        Binding("ctrl+r", "dictate", "Dictate", show=False),
        Binding("ctrl+x", "cancel", "Cancel turn", priority=True, show=False),
        Binding("f2", "cycle_autonomy", "Autonomy", show=False),  # fallback for ctrl+o
        Binding("f3", "cycle_phase", "Phase", show=False),        # fallback for ctrl+o
        Binding("ctrl+q", "quit", "Quit", show=False),
        Binding("ctrl+c", "quit", "Quit", show=False),
    ]

    # Shown in the Commands side panel (key, description). Includes prompt + slash commands
    # that aren't key bindings.
    COMMANDS = [
        ("Ctrl+B", "Toggle this commands panel"),
        ("Ctrl+P", "Pick / register a provider"),
        ("Ctrl+E", "Edit engagement (name, scope, ROE, windows, budget, report)"),
        ("Ctrl+O", "Set mode (autonomy / phase)"),
        ("Ctrl+T", "Capabilities (tools, skills, secrets, web backend)"),
        ("Ctrl+F", "Findings (confirm / reject candidates)"),
        ("Ctrl+R", "Dictate (push-to-talk, local)"),
        ("Ctrl+K", "Kill switch"),
        ("Ctrl+L", "Clear transcript"),
        ("Ctrl+Q", "Quit"),
        ("Enter", "Run the prompt  ·  Ctrl+J: newline"),
        ("/name", "Invoke a skill  ·  /compact · /save · /: list"),
        ("Session", "Auto-saves each turn & on quit; resumes on reopening the engagement"),
        ("↑/↓, Tab", "Navigate & complete slash suggestions"),
    ]

    def __init__(self, *, engagement: str | Path = DEFAULT_ENGAGEMENT) -> None:
        super().__init__()
        self.engagement_path = str(engagement)
        self.mode = self._load_mode()
        self.engine: Engine | None = None
        self.loop = None
        from hexharness.tui.config import load_selection

        # Reuse the provider chosen in a previous session (keys come from env/vault, not here).
        self._selection = load_selection() or {"kind": "provider", "keys": ["anthropic"], "model": ""}
        self._tokens = 0
        self._usd = 0.0
        self._live_buf = ""       # accumulating streamed text for the current model turn
        self._streamed = False    # did any text stream this run? (non-streaming providers: no)
        self._dictation = None    # lazy push-to-talk dictation (local Whisper)
        self._dict_base = ""      # prompt text present when dictation started
        self._skills = None       # lazy SkillRegistry for /slash skill references
        self._slash_sel = 0       # selected index in the live slash suggestions
        self._thinking_buf = ""   # accumulating model reasoning for the current turn
        self._saved_conversation = None  # carried across a loop rebuild (provider change)
        self._saved_tokens = 0
        self._eng_name = ""              # engagement name = session key for persistence
        self._resume_conv = None         # conversation loaded from a saved session
        self._queue: list[str] = []      # messages typed while a turn runs (drained in order)
        self._turn_running = False            # is a turn in flight?
        self._run_worker = None          # handle to the current run worker (for cancel)

    # --- layout ---

    def compose(self) -> ComposeResult:
        yield HexHeader(id="header")
        yield RichLog(id="transcript", wrap=True, markup=False, highlight=False)
        yield Static("", id="thinking")  # live model reasoning (dim) for the current turn
        yield Static("", id="live")  # live-streaming model text for the current turn
        yield Static("", id="slash-suggest")  # live skill suggestions while typing "/..."
        yield Static("ready — type a prompt", id="status")  # working / thinking / waiting
        # multi-line, soft-wrapping, auto-growing prompt (Enter submits, Ctrl+J newline)
        yield PromptArea(id="prompt", soft_wrap=True)
        yield Static(self._commands_text(), id="command-panel")  # toggleable (Ctrl+B)
        yield Footer()

    def _commands_text(self) -> str:
        rows = "\n".join(f"{k:<11} {d}" for k, d in self.COMMANDS)
        return f"Commands   (Ctrl+B to close)\n\n{rows}"

    def action_commands(self) -> None:
        panel = self.query_one("#command-panel", Static)
        panel.display = not panel.display

    def action_cancel(self) -> None:
        """Abort a stuck/running turn and clear the queue so the operator can continue."""
        if self._run_worker is not None:
            self._run_worker.cancel()
            self._run_worker = None
        # Drop the trailing unanswered user message so the next turn isn't two user turns.
        if self.loop is not None and self.loop.conversation and \
                getattr(self.loop.conversation[-1].role, "value", "") == "user":
            self.loop.conversation.pop()
        n = len(self._queue)
        self._queue.clear()
        self._turn_running = False
        self._set_status("cancelled — ready", _WARNING)
        self._log(f"⨯ cancelled current turn" + (f" and {n} queued" if n else ""), _WARNING)

    def on_mount(self) -> None:
        self._sync_header()
        prompt = self.query_one("#prompt", PromptArea)
        prompt.completer = self._selected_match  # Tab completes the selected match
        prompt.nav_fn = self._slash_nav          # up/down move the selection
        prompt.focus()
        self._log("HexHarness ready. Ctrl+P to pick a provider, then type a task.", _MUTED)
        self._announce_saved_session()

    def _announce_saved_session(self) -> None:
        """At launch, tell the operator if a saved session will resume (it loads lazily
        on the first prompt, so without this notice it isn't visible up front)."""
        try:
            from hexharness import session as sess
            from hexharness.engagement import Engagement

            name = Engagement.load(self.engagement_path).name
            if sess.exists(name):
                convo = sess.load_conversation(name)
                if convo:
                    self._log(f"↩ resuming '{name}' — {len(convo)} messages of history:", _SUCCESS)
                    self._render_history(convo)
                    self._log("— end of history, continue below —", _MUTED)
                else:
                    self._log(f"↩ saved session for '{name}' found (findings + event log resume "
                              "on your first prompt).", _SUCCESS)
        except Exception:  # noqa: BLE001 — a missing/bad engagement file is not fatal here
            pass

    def _render_history(self, messages) -> None:
        """Re-paint a resumed conversation into the transcript so the operator sees the
        past turns (the model already gets them as context; this is for visibility)."""
        from hexharness.providers.types import TextBlock, ToolResultBlock, ToolUseBlock

        for m in messages:
            is_user = getattr(m.role, "value", "") == "user"
            for b in m.content:
                if isinstance(b, TextBlock) and b.text.strip():
                    if is_user:
                        self._log(f"❯ {b.text}", _ACCENT)
                    else:
                        self._log_markdown(b.text)
                elif isinstance(b, ToolUseBlock):
                    self._log(f"→ {b.name} {b.input}", _MUTED)
                elif isinstance(b, ToolResultBlock):
                    mark = "✗" if b.is_error else "✓"
                    self._log(f"{mark} {b.content[:200]}", _MUTED)

    def _slash_token(self) -> str | None:
        """The slash prefix currently being typed, or None if not in slash mode."""
        text = self.query_one("#prompt", PromptArea).text
        if text.startswith("/") and " " not in text and "\n" not in text:
            return text[1:]
        return None

    def _slash_matches(self, prefix: str) -> list[str]:
        names = sorted(n for n in list_skills(self._skill_registry()) if n.lower().startswith(prefix.lower()))
        for cmd in ("compact", "save"):  # built-in commands shown alongside skills
            if cmd.startswith(prefix.lower()):
                names.append(cmd)
        return names

    def action_quit(self) -> None:
        self._save_session()  # persist the conversation before exiting
        self.exit()

    def _render_suggest(self, items: list[str]) -> None:
        suggest = self.query_one("#slash-suggest", Static)
        if not items:
            suggest.update("(no match)")
            suggest.display = True
            return
        self._slash_sel %= len(items)
        shown = "  ".join((f"▶ /{n}" if i == self._slash_sel else f"/{n}")
                           for i, n in enumerate(items))
        suggest.update(shown + "   ·  ↑/↓ select · Tab/Enter complete")
        suggest.display = True

    def _slash_nav(self, delta: int) -> None:
        token = self._slash_token()
        if token is None:
            return
        items = self._slash_matches(token)
        if items:
            self._slash_sel = (self._slash_sel + delta) % len(items)
            self._render_suggest(items)

    def _selected_match(self) -> str | None:
        token = self._slash_token()
        if token is None:
            return None
        items = self._slash_matches(token)
        return items[self._slash_sel % len(items)] if items else None

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
        if self.loop is not None and self.loop.last_input_tokens:
            from hexharness.providers.context_window import window_for

            used = self.loop.last_input_tokens
            win = window_for(self.loop._model_id())
            parts.append(f"ctx {used // 1000}k/{win // 1000}k  {used / win:.0%}")
        self.query_one("#header", HexHeader).update("  ·  ".join(parts))

    # --- transcript ---

    def _log(self, text: str, style: str = _TEXT) -> None:
        self.query_one("#transcript", RichLog).write(Text(text, style=style))

    def _log_markdown(self, text: str) -> None:
        """Render model output as Markdown (headings, tables, lists, code) in the transcript."""
        try:
            self.query_one("#transcript", RichLog).write(Markdown(text))
        except Exception:  # noqa: BLE001 — never let a render error drop the output
            self._log(text, _TEXT)

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
        # Idempotent: build the engine if missing, and (re)build the loop if missing,
        # carrying any saved conversation across a provider change.
        if self.engine is None:
            from hexharness import session as sess
            from hexharness.engagement import Engagement

            self._eng_name = Engagement.load(self.engagement_path).name
            resuming = sess.exists(self._eng_name)
            sess.db_path(self._eng_name).parent.mkdir(parents=True, exist_ok=True)
            provider = self._make_provider()  # may raise RuntimeError if a key is missing
            self.engine = Engine.from_engagement(
                self.engagement_path, provider=provider, requested_mode=self.mode,
                approver=TUIApprover(self), secret_requester=TUISecretRequester(self),
                db=str(sess.db_path(self._eng_name)),  # file-backed => events + findings persist
            )
            self.engine.events._bus.subscribe(self._on_event)
            if resuming:
                from hexharness.recovery.snapshot import Recovery

                state = Recovery.rebuild(self.engine.events.all())
                self.engine.control.budget.tokens_used = state.tokens_spent
                self._resume_conv = sess.load_conversation(self._eng_name)
                self._log(f"resumed session · {len(self.engine.events.all())} events · "
                          f"{len(self.engine.evidence.confirmed())} confirmed findings", _SUCCESS)
        if self.loop is None:
            provider = self._make_provider()
            self.loop = self.engine.loop(provider=provider, model=self._model_override(),
                                         on_text=self._stream_text, on_thinking=self._stream_thinking)
            if self._saved_conversation is not None:
                self.loop.conversation = self._saved_conversation
                self.loop.last_input_tokens = self._saved_tokens
                self._saved_conversation = None
            elif self._resume_conv is not None:
                self.loop.conversation = self._resume_conv
                self._resume_conv = None
        self._sync_header()

    def _save_session(self) -> None:
        if self.loop is not None and self._eng_name:
            from hexharness import session as sess

            sess.save_conversation(self._eng_name, self.loop.conversation)

    def _set_status(self, text: str, style: str = _MUTED) -> None:
        self.query_one("#status", Static).update(Text(text, style=style))

    def _stream_text(self, delta: str) -> None:
        """Token sink (runs on the app loop). Grow the live line; it's flushed into the
        transcript permanently when the turn's MODEL_RESPONSE event arrives."""
        self._streamed = True
        self._set_status("⣾ writing…", _ACCENT)
        self._live_buf += delta
        self.query_one("#live", Static).update(Text(self._live_buf, style=_TEXT))

    def _stream_thinking(self, delta: str) -> None:
        """Reasoning sink: show the model's thinking live, dimmed, above the answer."""
        self._set_status("💭 thinking…", _WARNING)
        self._thinking_buf += delta
        self.query_one("#thinking", Static).update(Text("💭 " + self._thinking_buf, style=_MUTED))

    def _flush_live(self) -> None:
        # Keep the reasoning in the scrollback (dim), before the answer — don't just hide it.
        if self._thinking_buf:
            self._log(f"💭 {self._thinking_buf}", _MUTED)
            self._thinking_buf = ""
        self.query_one("#thinking", Static).update("")
        if self._live_buf:
            self._log_markdown(self._live_buf)  # render the model answer as Markdown
            self._live_buf = ""
        self.query_one("#live", Static).update("")

    # --- running ---

    def _skill_registry(self):
        if self._skills is None:
            from pathlib import Path

            import hexharness.skills as pkg
            from hexharness.skills.engine import SkillRegistry

            lib = Path(pkg.__file__).parent / "library"
            self._skills = SkillRegistry().discover(lib) if lib.is_dir() else SkillRegistry()
        return self._skills

    @on(PromptArea.Changed, "#prompt")
    def _prompt_changed(self, event: PromptArea.Changed) -> None:
        """Live skill suggestions while typing a slash token (before the first space)."""
        token = self._slash_token()
        if token is not None:
            self._slash_sel = 0  # editing the token restarts the selection at the top
            self._render_suggest(self._slash_matches(token))
        else:
            self.query_one("#slash-suggest", Static).display = False

    @on(PromptArea.Submitted)
    def _submit(self, event: PromptArea.Submitted) -> None:
        prompt = event.text.strip()
        if not prompt:
            return
        self.query_one("#prompt", PromptArea).text = ""

        if prompt in ("/compact", "/compact "):
            self._compact()
            return
        if prompt in ("/save", "/save "):
            self._save_session()
            self._log("session saved — resume by reopening this engagement", _SUCCESS)
            return

        reg = self._skill_registry()
        if is_list_request(prompt):
            names = list_skills(reg)
            self._log("skills: " + (", ".join(f"/{n}" for n in names) or "(none)"), _MUTED)
            return
        prompt, used, unknown = expand_slash(prompt, reg)
        if unknown:
            names = list_skills(reg)
            self._log(f"unknown skill /{unknown} — available: "
                      + (", ".join(f"/{n}" for n in names) or "(none)"), _WARNING)
            return
        if used:
            self._log(f"using skill /{used}", _MUTED)
        if self._turn_running:
            self._queue.append(prompt)  # a turn is in flight — queue this one
            self._log(f"⏳ queued ({len(self._queue)}): {prompt}", _MUTED)
            self._set_status(f"working… · {len(self._queue)} queued  (Ctrl+X cancel)", _ACCENT)
            return
        self._run_worker = self._run(prompt)

    @work(group="scope")
    async def _propose_scope(self, path: str | None) -> None:
        """Operator approval for a model-proposed scope change. Approval is the ONLY way
        to apply it — the model cannot activate scope in any mode."""
        if not path or self.engine is None:
            return
        from hexharness.engagement import Engagement

        try:
            eng = Engagement.load(path)
        except Exception as exc:  # noqa: BLE001
            self._log(f"could not load proposed engagement: {exc}", _DANGER)
            return
        approved = await self.push_screen_wait(ScopeApprovalModal(eng))
        if not approved:
            self._log("scope change rejected", _MUTED)
            return
        await self.engine.apply_engagement(eng, approved_by="operator")
        if self.loop is not None:
            self.loop.ctx = self.engine.ctx  # live loop adopts the re-clamped context

    @work(exclusive=True, group="compact")
    async def _compact(self) -> None:
        if self.loop is None:
            self._log("nothing to compact yet — run a task first", _MUTED)
            return
        collapsed = await self.loop.compact(reason="manual")
        self._log(f"compacted {collapsed} messages into a summary" if collapsed
                  else "nothing to compact", _MUTED)
        self._sync_header()

    @work(exclusive=True)
    async def _run(self, prompt: str) -> None:
        # Input stays enabled so the operator can type and QUEUE more messages while a
        # turn runs; queued prompts drain one at a time when this turn finishes.
        self._turn_running = True
        self._log(f"❯ {prompt}", _ACCENT)
        self._live_buf = ""
        self._streamed = False
        self._thinking_buf = ""
        self._set_status("⣾ working…", _ACCENT)
        try:
            self._ensure_engine()
            # Hard ceiling: a turn can never hang the UI forever, whatever the cause
            # (provider, network, a stuck tool). Ctrl+X cancels sooner.
            result = await asyncio.wait_for(self.loop.run(prompt), timeout=600)
            self._flush_live()
            # Streaming already showed every turn's text; only write the return value
            # when nothing streamed (e.g. a provider that doesn't support on_text yet).
            if not self._streamed:
                self._log_markdown(result or "(no output)")
        except asyncio.TimeoutError:
            self._log("turn timed out (no response in 600s) — provider unreachable? "
                      "Try Ctrl+P to switch provider", _DANGER)
        except RuntimeError as exc:
            # Most likely a missing API key — point the operator at the provider screen.
            self._log(f"provider error: {exc}  (Ctrl+P to configure)", _DANGER)
            self.engine = None
        except Exception as exc:  # noqa: BLE001 — surface, never crash the UI
            self._log(f"error: {exc}", _DANGER)
        finally:
            self._turn_running = False
            self._save_session()  # auto-save the conversation after each turn
            self.query_one("#prompt", PromptArea).focus()
            if self._queue:
                nxt = self._queue.pop(0)
                self._set_status(f"next queued… · {len(self._queue)} left", _ACCENT)
                self._run_worker = self._run(nxt)  # drain the next queued message
            else:
                self._set_status("ready — type a prompt", _MUTED)

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
            self._set_status(f"🔧 running {p.get('tool')}…", _ACCENT)
            self._log(f"→ {p.get('tool')} {p.get('input', {})}", _MUTED)
        elif t is EventType.TOOL_FINISHED:
            mark = "✓" if p.get("ok") else "✗"
            extra = "" if p.get("ok") else f" — {p.get('error', '')}"
            self._log(f"{mark} {p.get('tool')}{extra}", _MUTED)
            out = (p.get("output") or "").rstrip()
            if out:
                self._log(out, _TEXT)
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
        elif t is EventType.CONTEXT_COMPACTED:
            self._log(f"context compacted ({p.get('reason')}): "
                      f"{p.get('messages_before')}→{p.get('messages_after')} messages", _WARNING)
        elif t is EventType.ENGAGEMENT_PROPOSED:
            self._log(f"scope change proposed: {p.get('name')} — approve in the dialog", _WARNING)
            self._propose_scope(p.get("path"))
        elif t is EventType.SCOPE_CHANGED:
            self._log(f"scope changed (approved by {p.get('approved_by')}): {p.get('engagement')}", _SUCCESS)
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
        from hexharness.tui.config import save_custom_provider, save_selection

        if result.get("kind") == "custom":
            # Freshly registered bring-your-own gateway: persist it (key included) to the
            # secret store, then store a normal named selection so it reloads next session.
            p = result["params"]
            save_custom_provider({"name": p["name"], "base_url": p["base_url"],
                                  "model": p["model"], "api_key": p["api_key"]})
            result = {"kind": "provider", "keys": [f"custom:{providers._slug(p['name'])}"],
                      "model": p["model"]}
        self._selection = result
        save_selection(result)  # persist for future sessions (never contains an api key)
        # Keep the engine (events/evidence/scope) and the conversation; only the loop is
        # rebuilt with the new provider on the next run, carrying the history over.
        if self.loop is not None:
            self._saved_conversation = self.loop.conversation
            self._saved_tokens = self.loop.last_input_tokens
        self.loop = None
        self._sync_header()
        self._log(f"provider set: {self._provider_model()[0]}  (saved for next session)", _MUTED)

    @staticmethod
    def _load_mode() -> Mode:
        from hexharness.tui.config import load_mode

        m = load_mode()
        if m:
            try:
                return Mode(autonomy=Autonomy[m["autonomy"].upper()], phase=Phase[m["phase"].upper()])
            except Exception:  # noqa: BLE001 — bad/old value => default
                pass
        return Mode(autonomy=Autonomy.INTERACTIVE, phase=Phase.RECON)

    def _current_roe(self) -> dict:
        from hexharness.engagement import Engagement

        eng = self.engine.engagement if self.engine is not None else Engagement.load(self.engagement_path)
        return {"max_risk": eng.roe.max_risk, "max_autonomy": eng.roe.max_autonomy,
                "max_phase": eng.roe.max_phase}

    async def _apply_roe(self, roe_update: dict) -> None:
        """Persist + apply a ROE ceiling change (deliberate human action, audited)."""
        from hexharness.engagement import Engagement
        from hexharness.engagement_builder import EngagementSpec, render_yaml

        base = self.engine.engagement if self.engine is not None else Engagement.load(self.engagement_path)
        if all(getattr(base.roe, k) == v for k, v in roe_update.items()):
            return  # unchanged
        data = base.model_dump()
        data["roe"].update(roe_update)
        try:
            new_eng = Engagement.model_validate(data)
            yaml_text = render_yaml(EngagementSpec.model_validate(new_eng.model_dump()))
        except Exception as exc:  # noqa: BLE001
            self._log(f"invalid ROE — not applied: {exc}", _DANGER)
            return
        Path(self.engagement_path).write_text(yaml_text)
        if self.engine is not None:
            await self.engine.apply_engagement(new_eng, approved_by="operator")

    @work
    async def action_mode(self) -> None:
        result = await self.push_screen_wait(ModeScreen(mode=self.mode, roe=self._current_roe()))
        if result is None:
            return
        self.mode = result["mode"]
        from hexharness.tui.config import save_mode

        save_mode(self.mode.autonomy.name.lower(), self.mode.phase.name.lower())  # persist across sessions
        await self._apply_roe(result["roe"])   # raise/lower the hard ceiling
        self._reset_mode()                       # re-clamp the ctx mode to the ROE, in place
        self._log(f"mode set: {self.mode.autonomy.name.lower()}/{self.mode.phase.name.lower()}", _MUTED)

    @work(group="scope")
    async def action_edit_scope(self) -> None:
        """Full engagement editor: the operator edits every setting directly (no model
        involved), then we validate, persist to the engagement file, and apply it live if
        running. This editor IS the human action, so applying needs no extra approval modal.
        The screen returns a COMPLETE engagement-data dict ready for model_validate."""
        from hexharness.engagement import Engagement
        from hexharness.engagement_builder import EngagementSpec, render_yaml

        base = self.engine.engagement if self.engine is not None else Engagement.load(self.engagement_path)
        result = await self.push_screen_wait(EngagementEditScreen(engagement=base))
        if result is None:
            return
        try:
            # model_validate coerces/validates every field (budget numbers included);
            # render_yaml builds the runtime scope guard + ROE, so a bad CIDR, number or
            # time window raises HERE — before we persist or apply.
            new_eng = Engagement.model_validate(result)
            yaml_text = render_yaml(EngagementSpec.model_validate(new_eng.model_dump()))
        except Exception as exc:  # noqa: BLE001 — surface the invalid engagement, don't apply
            self._log(f"invalid engagement — not applied: {exc}", _DANGER)
            return

        Path(self.engagement_path).write_text(yaml_text)  # survives restart
        if self.engine is not None:
            await self.engine.apply_engagement(new_eng, approved_by="operator")
            if self.loop is not None:
                self.loop.ctx = self.engine.ctx  # live loop adopts the re-clamped context
            # SCOPE_CHANGED is logged by the existing _on_event handler.
        else:
            self._log("engagement saved — applies on the next run", _SUCCESS)
            self._sync_header()

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

    @work
    async def action_findings(self) -> None:
        # Build the engine so the panel reads the live evidence store; if no provider key
        # is configured yet the screen shows its empty-state note (never crash the UI).
        try:
            self._ensure_engine()
        except RuntimeError:
            pass
        await self.push_screen_wait(FindingsScreen(engine=self.engine))

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
        # Update the context mode IN PLACE (re-clamped by ROE) so the conversation, event
        # log and evidence are preserved — rebuilding the engine would wipe them.
        if self.engine is not None:
            self.engine.ctx = ExecContext(
                engagement_id=self.engine.ctx.engagement_id,
                subagent_id=self.engine.ctx.subagent_id,
                mode=self.engine.engagement.clamp(self.mode),
                now=self.engine.ctx.now,
            )
            if self.loop is not None:
                self.loop.ctx = self.engine.ctx
        self._sync_header()
