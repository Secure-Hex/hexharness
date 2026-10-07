"""PromptArea — a multi-line prompt that soft-wraps and grows with its content.

A long prompt (e.g. live dictation, which produces one unbroken line) wraps and the
box grows in height instead of scrolling off to the side. Enter submits; Ctrl+J inserts
a newline. Height is driven by the WRAPPED (visual) line count, capped so it never eats
the whole screen.
"""
from __future__ import annotations

from textual import events
from textual.message import Message
from textual.widgets import TextArea


class PromptArea(TextArea):
    MIN_ROWS = 1
    MAX_ROWS = 12  # beyond this the box scrolls internally instead of growing further
    completer = None  # app sets this: callable() -> selected match | None (Tab-complete)
    nav_fn = None     # app sets this: callable(delta:int) -> None (up/down through matches)

    class Submitted(Message):
        def __init__(self, text: str) -> None:
            self.text = text
            super().__init__()

    def on_mount(self) -> None:
        self._autogrow()

    def on_resize(self, event: events.Resize) -> None:
        # width changed => wrapping changed => recompute height
        self._autogrow()

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        self._autogrow()

    def _autogrow(self) -> None:
        try:
            rows = self.wrapped_document.height  # visual rows, wrapping included
        except Exception:  # noqa: BLE001 — before first layout
            rows = self.document.line_count
        rows = max(self.MIN_ROWS, min(self.MAX_ROWS, rows or 1))
        self.styles.height = rows + 2  # + rounded border (top + bottom)

    async def _on_key(self, event: events.Key) -> None:
        text = self.text
        slash_active = text.startswith("/") and " " not in text and "\n" not in text
        if slash_active and self.nav_fn is not None and event.key in ("up", "down"):
            event.prevent_default()
            event.stop()
            self.nav_fn(-1 if event.key == "up" else 1)
            return
        if slash_active and event.key in ("tab", "enter") and self.completer is not None:
            match = self.completer()
            if match:  # Enter/Tab complete the selection; a non-matching "/x" still submits
                event.prevent_default()
                event.stop()
                self.text = f"/{match} "
                self.move_cursor(self.document.end)
                return
        if event.key == "enter":
            event.prevent_default()
            event.stop()
            self.post_message(self.Submitted(self.text))
            return
        if event.key == "ctrl+j":  # reliable newline (shift+enter isn't distinguishable)
            event.prevent_default()
            event.stop()
            self.insert("\n")
            return
        await super()._on_key(event)
