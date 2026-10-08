"""web_search — OSINT web search with pluggable backends.

Default backend is DuckDuckGo via `ddgs` (free, no key). If a Tavily or Exa API key is
present in the Vault/env, that cleaner backend is used instead. Paid-backend keys are
read from the Vault (set out-of-band), never passed in by the model.

Classification: ACTIVE (reaches the internet) but NOT scope_sensitive — the query is
OSINT, not an engagement target. Opsec note: any web search sends the QUERY to a third
party; that egress is inherent to searching the web.
"""
from __future__ import annotations

import asyncio
import json
import urllib.request
from typing import Callable

from pydantic import BaseModel, Field

from hexharness.tools.base import RiskLevel, Tool

Result = dict  # {"title": str, "url": str, "snippet": str}


class WebSearchInput(BaseModel):
    query: str = Field(description="Search query")
    max_results: int = Field(default=5, ge=1, le=20)


def _ddgs_search(query: str, k: int) -> list[Result]:
    from ddgs import DDGS  # optional [search] dep

    with DDGS() as ddgs:
        rows = ddgs.text(query, max_results=k)
    return [{"title": r.get("title", ""), "url": r.get("href", ""), "snippet": r.get("body", "")}
            for r in rows]


def _post_json(url: str, payload: dict, headers: dict) -> dict:
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json", **headers})
    with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310 — fixed provider URLs
        return json.loads(resp.read().decode())


def _tavily_search(api_key: str, query: str, k: int) -> list[Result]:
    body = _post_json("https://api.tavily.com/search",
                      {"api_key": api_key, "query": query, "max_results": k}, {})
    return [{"title": r.get("title", ""), "url": r.get("url", ""), "snippet": r.get("content", "")}
            for r in body.get("results", [])]


def _exa_search(api_key: str, query: str, k: int) -> list[Result]:
    body = _post_json("https://api.exa.ai/search",
                      {"query": query, "numResults": k, "contents": {"text": True}},
                      {"x-api-key": api_key})
    return [{"title": r.get("title", ""), "url": r.get("url", ""),
             "snippet": (r.get("text") or "")[:300]} for r in body.get("results", [])]


class WebSearchTool(Tool):
    name = "web_search"
    description = (
        "Search the web for OSINT. Uses a free DuckDuckGo backend by default; if a Tavily "
        "or Exa API key is configured it uses that for cleaner results. Input: query, "
        "optional max_results."
    )
    input_model = WebSearchInput
    risk_level = RiskLevel.ACTIVE
    scope_sensitive = False
    requires_approval = False

    def __init__(self, vault=None, *, search_fn: Callable[[str, int], list[Result]] | None = None):
        self.vault = vault
        self._search_fn = search_fn  # test/override hook

    def active_backend(self) -> str:
        """Name of the backend that a search would use right now (for the UI)."""
        return self._select_backend()[0]

    def _select_backend(self) -> tuple[str, Callable[[str, int], list[Result]]]:
        if self._search_fn is not None:
            return "injected", self._search_fn
        v = self.vault
        if v is not None and v.has("TAVILY_API_KEY"):
            return "tavily", lambda q, k: _tavily_search(v.get("TAVILY_API_KEY"), q, k)
        if v is not None and v.has("EXA_API_KEY"):
            return "exa", lambda q, k: _exa_search(v.get("EXA_API_KEY"), q, k)
        return "duckduckgo", _ddgs_search

    async def run(self, tool_input: dict) -> str:
        data = WebSearchInput.model_validate(tool_input)
        backend, fn = self._select_backend()
        try:
            results = await asyncio.to_thread(fn, data.query, data.max_results)
        except ImportError:
            return "web_search: install the free backend with  pip install -U 'hexharness[search]'"
        except Exception as exc:  # noqa: BLE001 — surface the failure to the agent, don't crash
            return f"web_search error ({backend}): {exc}"
        if not results:
            return f"[{backend}] no results for {data.query!r}"
        lines = [f"[{backend}] {len(results)} results for {data.query!r}:"]
        for r in results:
            lines.append(f"- {r['title']}\n  {r['url']}\n  {r['snippet'][:200]}")
        return "\n".join(lines)
