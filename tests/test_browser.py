"""browser tool: drives steps + screenshot via an injected session (no real Playwright)."""
from __future__ import annotations

from hexharness.tools.base import RiskLevel
from hexharness.tools.native.browser import BrowserTool


def test_fields():
    t = BrowserTool("/tmp/ws")
    assert t.scope_sensitive and t.target_field == "url" and t.risk_level is RiskLevel.ACTIVE


async def test_runs_steps_and_reports(tmp_path):
    seen = {}

    async def fake_session(url, steps, shot_path, timeout):
        seen["url"] = url
        seen["steps"] = steps
        seen["shot"] = shot_path
        return {"status": 200, "title": "Login", "text": "Welcome admin",
                "screenshot": shot_path,
                "step_results": [{"action": "fill", "result": "filled"},
                                 {"action": "click", "result": "clicked"}]}

    tool = BrowserTool(tmp_path, session_fn=fake_session)
    out = await tool.run({
        "url": "https://app.acme.example/login",
        "steps": [{"action": "fill", "selector": "#user", "value": "admin"},
                  {"action": "click", "selector": "#submit"}],
        "screenshot": True,
    })
    assert "200 https://app.acme.example/login" in out and "title: Login" in out
    assert "filled" in out and "clicked" in out
    assert "Welcome admin" in out
    assert seen["shot"] and seen["shot"].endswith(".png")        # screenshot path in workspace
    assert seen["steps"][0]["selector"] == "#user"


async def test_missing_playwright_message(tmp_path):
    from hexharness.tools.native.browser import _MissingPlaywright

    async def no_pw(*a, **k):
        raise _MissingPlaywright

    out = await BrowserTool(tmp_path, session_fn=no_pw).run({"url": "https://app.acme.example"})
    assert "pip install" in out and "playwright install chromium" in out
