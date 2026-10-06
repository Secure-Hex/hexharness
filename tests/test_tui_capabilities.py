"""Capabilities panel + masked secret modal. Skipped if Textual isn't installed."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

pytest.importorskip("textual")

from textual.widgets import Input, Label  # noqa: E402

from hexharness.tui.app import HexTUI  # noqa: E402
from hexharness.tui.approver import TUISecretRequester  # noqa: E402
from hexharness.tui.screens import CapabilitiesScreen, SecretModal  # noqa: E402


def _fake_tool(name: str, risk: str, *, approval: bool = False, scope: bool = False):
    return SimpleNamespace(
        name=name, risk_level=SimpleNamespace(name=risk),
        requires_approval=approval, scope_sensitive=scope,
    )


def _fake_engine():
    tools = {
        "cwe.lookup": _fake_tool("cwe.lookup", "PASSIVE"),
        "dns.lookup": _fake_tool("dns.lookup", "ACTIVE", scope=True),
        "exploit.run": _fake_tool("exploit.run", "INTRUSIVE", approval=True, scope=True),
    }
    return SimpleNamespace(
        registry=SimpleNamespace(_tools=tools),
        vault=SimpleNamespace(names=lambda: ["ANTHROPIC_API_KEY", "TARGET_API_KEY"]),
    )


# --- capabilities panel ---

async def test_capabilities_renders_tools_and_secret_names_only():
    app = HexTUI()
    async with app.run_test() as pilot:
        screen = CapabilitiesScreen(engine=_fake_engine(), provider="anthropic", model="claude-x")
        await app.push_screen(screen)
        await pilot.pause()
        await pilot.pause()
        text = "\n".join(str(w.render()) for w in screen.query(Label))

        # provider/model + every tool with its risk level
        assert "anthropic/claude-x" in text
        assert "dns.lookup" in text and "active" in text
        assert "exploit.run" in text and "requires approval" in text  # approval badge
        # secret NAMES only — never a value (names() returns names; no value is ever read)
        assert "ANTHROPIC_API_KEY" in text and "TARGET_API_KEY" in text
        assert "sk-" not in text  # no key value leaked into the panel


async def test_capabilities_opens_from_binding_without_engine():
    # No provider key configured -> engine can't build -> static catalog + graceful note.
    app = HexTUI()
    async with app.run_test() as pilot:
        await pilot.press("ctrl+t")
        await pilot.pause()
        await pilot.pause()
        assert isinstance(app.screen, CapabilitiesScreen)
        text = "\n".join(str(w.render()) for w in app.screen.query(Label))
        assert "cwe" in text.lower()  # a tool from the static default registry rendered


# --- masked secret modal ---

async def test_secret_modal_is_masked_and_returns_value():
    app = HexTUI()
    async with app.run_test() as pilot:
        results: list[str | None] = []
        modal = SecretModal(name="X_API_KEY", reason="tool needs it")
        await app.push_screen(modal, results.append)
        await pilot.pause()
        box = modal.query_one("#secret-value", Input)
        assert box.password is True  # MASKED
        box.value = "sk-pasted-secret"
        await pilot.press("enter")
        await pilot.pause()
        assert results == ["sk-pasted-secret"]


async def test_secret_requester_resolves_via_push_screen():
    class _StubApp:
        def push_screen(self, screen, callback):
            assert isinstance(screen, SecretModal)
            callback("sk-xyz")

    req = TUISecretRequester(_StubApp())
    assert await req.request(name="X", reason="r") == "sk-xyz"


async def test_secret_requester_cancel_returns_none():
    class _StubApp:
        def push_screen(self, screen, callback):
            callback(None)

    req = TUISecretRequester(_StubApp())
    assert await req.request(name="X", reason="r") is None
