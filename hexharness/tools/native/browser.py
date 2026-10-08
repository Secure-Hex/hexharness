"""browser — drive a headless browser (Playwright) to interact with a web app and take
screenshots. Scope-sensitive: the Scope Guard checks the initial URL's host. Screenshots
are written to the engagement workspace (on the host, so the operator can open them).

Playwright is an optional dep ([browser]) and needs its browser installed:
    pip install -U 'hexharness[browser]' && playwright install chromium
The browser session is injectable so tests run without a real browser.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Awaitable, Callable

from pydantic import BaseModel, Field

from hexharness.tools.base import RiskLevel, Tool


class BrowserStep(BaseModel):
    action: str = Field(description="goto | click | fill | press | text | wait | screenshot")
    selector: str | None = Field(default=None, description="CSS selector (for click/fill/press/text)")
    value: str | None = Field(default=None, description="text to fill / key to press / url / ms to wait")


class BrowserInput(BaseModel):
    url: str = Field(description="Initial URL to open (its host must be in engagement scope)")
    steps: list[BrowserStep] = Field(default_factory=list, description="Interactions after load")
    screenshot: bool = Field(default=True, description="Capture a full-page screenshot at the end")
    timeout: int = Field(default=30, ge=1, le=120)


class BrowserTool(Tool):
    name = "browser"
    description = (
        "Drive a headless browser (Playwright): open a URL, interact (click/fill/press/wait), "
        "read page text, and capture screenshots to the workspace. Steps are a list of "
        "{action, selector?, value?}. Use for web app testing and visual evidence."
    )
    input_model = BrowserInput
    risk_level = RiskLevel.ACTIVE
    scope_sensitive = True
    requires_approval = False
    target_field = "url"

    def __init__(self, workspace: str | Path, *, session_fn: Callable[..., Awaitable[dict]] | None = None):
        self.workspace = Path(workspace)
        self._session_fn = session_fn  # inject for tests; default drives real Playwright

    async def run(self, tool_input: dict) -> str:
        data = BrowserInput.model_validate(tool_input)
        self.workspace.mkdir(parents=True, exist_ok=True)
        shot_path = self.workspace / f"screenshot-{int(time.time())}.png" if data.screenshot else None
        session = self._session_fn or _playwright_session
        try:
            result = await session(data.url, [s.model_dump() for s in data.steps],
                                   str(shot_path) if shot_path else None, data.timeout)
        except _MissingPlaywright:
            return ("browser needs Playwright: pip install -U 'hexharness[browser]' && playwright install chromium")
        except Exception as exc:  # noqa: BLE001 — surface, don't crash the turn
            return f"browser error: {exc}"
        lines = [f"{result.get('status', '?')} {data.url} — title: {result.get('title', '')}"]
        for i, out in enumerate(result.get("step_results", [])):
            if out:
                lines.append(f"  step {i} ({out.get('action')}): {str(out.get('result',''))[:200]}")
        if result.get("screenshot"):
            lines.append(f"  screenshot: {result['screenshot']}")
        body = (result.get("text") or "").strip()
        if body:
            lines.append(f"  page text (truncated):\n{body[:1500]}")
        return "\n".join(lines)


class _MissingPlaywright(Exception):
    pass


async def _playwright_session(url: str, steps: list[dict], shot_path: str | None, timeout: int) -> dict:
    try:
        from playwright.async_api import async_playwright
    except ImportError as exc:  # noqa: BLE001
        raise _MissingPlaywright from exc

    step_results: list[dict] = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            page = await browser.new_page()
            resp = await page.goto(url, timeout=timeout * 1000)
            status = resp.status if resp else "?"
            for step in steps:
                act, sel, val = step.get("action"), step.get("selector"), step.get("value")
                out = None
                if act == "goto" and val:
                    r = await page.goto(val, timeout=timeout * 1000)
                    out = r.status if r else "?"
                elif act == "click" and sel:
                    await page.click(sel, timeout=timeout * 1000)
                    out = "clicked"
                elif act == "fill" and sel is not None:
                    await page.fill(sel, val or "")
                    out = "filled"
                elif act == "press" and sel is not None:
                    await page.press(sel, val or "Enter")
                    out = "pressed"
                elif act == "text":
                    out = await page.inner_text(sel or "body")
                elif act == "wait":
                    if sel:
                        await page.wait_for_selector(sel, timeout=timeout * 1000)
                        out = "selector appeared"
                    else:
                        await page.wait_for_timeout(int(val or 1000))
                        out = "waited"
                elif act == "screenshot" and shot_path:
                    await page.screenshot(path=shot_path, full_page=True)
                    out = shot_path
                step_results.append({"action": act, "result": out})
            title = await page.title()
            text = await page.inner_text("body")
            if shot_path:
                await page.screenshot(path=shot_path, full_page=True)
            return {"status": status, "title": title, "text": text,
                    "screenshot": shot_path, "step_results": step_results}
        finally:
            await browser.close()
