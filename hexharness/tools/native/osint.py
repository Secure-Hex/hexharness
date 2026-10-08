"""OSINT/recon tools — all network I/O goes through an injected fn so tests need no net.

- WaybackUrlsTool:      PASSIVE, scope-sensitive, archived URLs from the Wayback CDX API (stdlib urllib).
- GithubDorkTool:       PASSIVE, GitHub code search for secrets/refs; reads GITHUB_TOKEN from the Vault.
- CloudStorageEnumTool: ACTIVE,  probes S3/Azure/GCS bucket URL patterns; requires approval.
"""
from __future__ import annotations

import asyncio
import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable

from pydantic import BaseModel, Field

from hexharness.tools.base import RiskLevel, Tool


# ------------------------------------------------------------- Wayback (native) --

class WaybackUrlsInput(BaseModel):
    domain: str = Field(description="Domain to pull archived URLs for (must be in engagement scope)")
    limit: int = Field(default=100, description="Max URLs to request from the CDX API")


class WaybackUrlsTool(Tool):
    name = "wayback_urls"
    description = "Fetch archived URLs for a domain from the Wayback Machine CDX API. Passive, no packets at target."
    input_model = WaybackUrlsInput
    risk_level = RiskLevel.PASSIVE
    scope_sensitive = True
    requires_approval = False
    target_field = "domain"

    def __init__(self, *, fetch_fn: Callable[[str], str] | None = None):
        self._fetch_fn = fetch_fn  # inject for tests; default = stdlib urllib

    async def run(self, tool_input: dict) -> str:
        domain = tool_input["domain"]
        limit = int(tool_input.get("limit", 100))
        url = ("http://web.archive.org/cdx/search/cdx?"
               + urllib.parse.urlencode({"url": f"{domain}/*", "output": "json",
                                         "fl": "original", "collapse": "urlkey", "limit": limit}))
        fetch = self._fetch_fn or _urllib_fetch
        try:
            raw = await asyncio.to_thread(fetch, url)
        except Exception as exc:  # noqa: BLE001 — network/timeout
            return f"wayback failed: {exc}"
        try:
            rows = json.loads(raw)
        except json.JSONDecodeError as exc:
            return f"wayback returned non-JSON: {exc}"
        # CDX JSON: first row is the header (["original"]); the rest are single-col url rows.
        urls = list(dict.fromkeys(r[0] for r in rows[1:] if r))
        if not urls:
            return f"wayback: no archived URLs for {domain}"
        shown = urls[:200]  # ponytail: cap output; raise the slice if a turn needs more
        more = f"\n… (+{len(urls) - len(shown)} more)" if len(urls) > len(shown) else ""
        return f"Archived URLs for {domain} ({len(urls)}):\n" + "\n".join(shown) + more


def _urllib_fetch(url: str) -> str:
    with urllib.request.urlopen(url, timeout=20) as resp:  # noqa: S310 — fixed web.archive.org host
        return resp.read().decode(errors="replace")


# ----------------------------------------------------------- GitHub dork (vault) --

class GithubDorkInput(BaseModel):
    query: str = Field(description="GitHub code-search query, e.g. 'org:acme AWS_SECRET'")
    per_page: int = Field(default=30, description="Max results to request (1-100)")


class GithubDorkTool(Tool):
    name = "github_dork"
    description = (
        "Search GitHub code for secrets/references via the code search API. Needs a GitHub token — "
        "the operator is prompted for it once, out of band, if it isn't set yet."
    )
    input_model = GithubDorkInput
    risk_level = RiskLevel.PASSIVE
    scope_sensitive = False
    requires_approval = False
    required_secrets = ["GITHUB_TOKEN"]  # the control plane resolves this before run()

    def __init__(self, vault, *, fetch_fn: Callable[[str, str], str] | None = None):
        self.vault = vault
        self._fetch_fn = fetch_fn  # inject for tests; default = stdlib urllib w/ auth header

    async def run(self, tool_input: dict) -> str:
        query = tool_input["query"]
        per_page = max(1, min(100, int(tool_input.get("per_page", 30))))
        token = self.vault.get("GITHUB_TOKEN")  # present: the control plane just ensured it
        url = ("https://api.github.com/search/code?"
               + urllib.parse.urlencode({"q": query, "per_page": per_page}))
        fetch = self._fetch_fn or _github_fetch
        try:
            raw = await asyncio.to_thread(fetch, url, token)
        except Exception as exc:  # noqa: BLE001 — network/timeout/403
            return f"github_dork failed: {exc}"
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            return f"github_dork returned non-JSON: {exc}"
        items = data.get("items", [])
        if not items:
            return f"github_dork: no code matches for {query!r} (total={data.get('total_count', 0)})"
        hits = [f"  {it.get('repository', {}).get('full_name', '?')}  {it.get('path', '?')}  {it.get('html_url', '')}".rstrip()
                for it in items[:per_page]]
        return f"github_dork {query!r} — {data.get('total_count', len(hits))} match(es):\n" + "\n".join(hits)


def _github_fetch(url: str, token: str) -> str:
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "hexharness",
    })
    with urllib.request.urlopen(req, timeout=20) as resp:  # noqa: S310 — fixed api.github.com host
        return resp.read().decode(errors="replace")


# ------------------------------------------------------- Cloud storage enum (http) --

class CloudStorageEnumInput(BaseModel):
    name: str = Field(description="Base name/slug to probe as a bucket (e.g. 'acme-prod')")
    extra: list[str] = Field(default=[], description="Extra candidate names to probe")


class CloudStorageEnumTool(Tool):
    name = "cloud_storage_enum"
    description = "Probe common S3/Azure Blob/GCS bucket URL patterns for a name and report which are reachable/public."
    input_model = CloudStorageEnumInput
    risk_level = RiskLevel.ACTIVE
    scope_sensitive = False
    requires_approval = True

    def __init__(self, *, http_fn: Callable[[str], tuple[int, str]] | None = None):
        self._http_fn = http_fn  # inject for tests; default = stdlib urllib GET

    async def run(self, tool_input: dict) -> str:
        names = list(dict.fromkeys([tool_input["name"], *tool_input.get("extra", [])]))
        http = self._http_fn or _http_get
        lines = [f"Cloud storage probe for: {', '.join(names)}"]
        for name in names:
            for url in _bucket_candidates(name):
                try:
                    status, body = await asyncio.to_thread(http, url)
                except Exception as exc:  # noqa: BLE001 — catch per-candidate, keep going
                    lines.append(f"  [err ] {url}  ({type(exc).__name__})")
                    continue
                lines.append(f"  [{_verdict(status, body):4s}] {url}  ({status})")
        return "\n".join(lines)


def _bucket_candidates(name: str) -> list[str]:
    return [
        f"https://{name}.s3.amazonaws.com",
        f"https://{name}.blob.core.windows.net",
        f"https://storage.googleapis.com/{name}",
    ]


def _verdict(status: int, body: str) -> str:
    # 200 = listable/public; 403 = exists but private; 404/NoSuchBucket = absent.
    if status == 200:
        return "PUB"
    if status in (401, 403):
        return "priv"
    if status == 404 or "NoSuchBucket" in body:
        return "none"
    return str(status)


def _http_get(url: str) -> tuple[int, str]:
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:  # noqa: S310 — operator-approved probe
            return resp.status, resp.read(2048).decode(errors="replace")
    except urllib.error.HTTPError as exc:  # 403/404 are signal, not failure
        return exc.code, exc.read(2048).decode(errors="replace") if exc.fp else ""
