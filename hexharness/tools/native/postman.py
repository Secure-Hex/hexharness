"""Postman collection tools.

Postman collections (v2.1 JSON) are a common artifact in API pentests — they enumerate
an API's endpoints, methods, headers and bodies. Two tools:

- postman_list: read a local collection and list its requests. PASSIVE, no network.
- postman_run: execute ONE named request against a scope-checked base_url. The collection
  supplies the path/method/headers/body; the host comes from base_url (which the Scope
  Guard validates), so a collection can never aim a request at an out-of-scope host.
  INTRUSIVE + requires_approval (collections can POST/PUT/DELETE).

# ponytail: parses + sends with stdlib urllib (no newman/node dep). Pulling a collection
# from the Postman cloud API (POSTMAN_API_KEY via the secret flow) is an easy follow-on tool.
"""
from __future__ import annotations

import asyncio
import json
import urllib.request
from pathlib import Path
from typing import Any, Callable

from pydantic import BaseModel, Field

from hexharness.tools.base import RiskLevel, Tool


class _Request(BaseModel):
    name: str
    method: str = "GET"
    path: str = "/"
    headers: dict[str, str] = Field(default_factory=dict)
    body: str | None = None


def parse_collection(data: dict) -> list[_Request]:
    """Flatten a Postman v2.1 collection (recursing folders) into leaf requests."""
    out: list[_Request] = []

    def _path_of(url: Any) -> str:
        if isinstance(url, str):
            from urllib.parse import urlparse

            u = urlparse(url)
            return u.path + (f"?{u.query}" if u.query else "") or "/"
        if isinstance(url, dict):
            if url.get("raw"):
                return _path_of(url["raw"])
            segs = url.get("path") or []
            return "/" + "/".join(str(s) for s in segs)
        return "/"

    def _walk(items: list[dict]) -> None:
        for item in items or []:
            if "item" in item:  # folder
                _walk(item["item"])
                continue
            req = item.get("request")
            if not req:
                continue
            headers = {h["key"]: h.get("value", "") for h in (req.get("header") or []) if "key" in h}
            body = (req.get("body") or {}).get("raw")
            out.append(_Request(
                name=item.get("name", "unnamed"),
                method=(req.get("method") or "GET").upper(),
                path=_path_of(req.get("url")),
                headers=headers,
                body=body,
            ))

    _walk(data.get("item", []))
    return out


def _load(collection_path: str) -> list[_Request]:
    raw = Path(collection_path).read_text()
    return parse_collection(json.loads(raw))


class PostmanListInput(BaseModel):
    collection_path: str = Field(description="Path to a Postman v2.1 collection .json")


class PostmanListTool(Tool):
    name = "postman_list"
    description = "List the requests (name, method, path) in a local Postman collection."
    input_model = PostmanListInput
    risk_level = RiskLevel.PASSIVE
    scope_sensitive = False
    requires_approval = False

    async def run(self, tool_input: dict) -> str:
        reqs = _load(tool_input["collection_path"])
        if not reqs:
            return "collection has no requests"
        return "\n".join(f"- {r.name}: {r.method} {r.path}" for r in reqs)


class PostmanRunInput(BaseModel):
    collection_path: str
    request_name: str = Field(description="Name of the request to execute (from postman_list)")
    base_url: str = Field(description="Target base URL; its host is scope-checked")
    timeout: int = Field(default=30, ge=1, le=120)


class PostmanRunTool(Tool):
    name = "postman_run"
    description = (
        "Execute ONE request from a Postman collection against base_url (the collection's "
        "method/path/headers/body, the given host). Intrusive — requires approval."
    )
    input_model = PostmanRunInput
    risk_level = RiskLevel.INTRUSIVE
    scope_sensitive = True
    requires_approval = True
    target_field = "base_url"

    def __init__(self, *, send_fn: Callable[..., tuple[int, str]] | None = None):
        self._send_fn = send_fn  # test/override hook

    async def run(self, tool_input: dict) -> str:
        data = PostmanRunInput.model_validate(tool_input)
        reqs = {r.name.lower(): r for r in _load(data.collection_path)}
        req = reqs.get(data.request_name.lower())
        if req is None:
            return f"request {data.request_name!r} not in collection (have: {', '.join(reqs) or 'none'})"
        url = data.base_url.rstrip("/") + req.path
        send = self._send_fn or _http_send
        try:
            status, body = await asyncio.to_thread(send, req.method, url, req.headers, req.body, data.timeout)
        except Exception as exc:  # noqa: BLE001
            return f"postman_run error: {exc}"
        return f"{req.method} {url} -> {status}\n{body[:800]}"


def _http_send(method: str, url: str, headers: dict, body: str | None, timeout: int) -> tuple[int, str]:
    data = body.encode() if body else None
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 — scope-checked host
            return resp.status, resp.read().decode(errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(errors="replace")
