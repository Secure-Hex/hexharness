"""Postman collection parse/list/run. Run uses an injected sender (no network) and the
host comes from base_url so the Scope Guard governs it."""
from __future__ import annotations

import json

from hexharness.tools.native.postman import PostmanListTool, PostmanRunTool, parse_collection

_COLLECTION = {
    "info": {"name": "acme-api", "schema": "v2.1.0"},
    "item": [
        {"name": "Login", "request": {
            "method": "POST", "url": {"raw": "https://old.example/api/v1/login", "path": ["api", "v1", "login"]},
            "header": [{"key": "Content-Type", "value": "application/json"}],
            "body": {"raw": "{\"u\":\"admin\"}"}}},
        {"name": "Users folder", "item": [
            {"name": "List users", "request": {"method": "GET", "url": {"path": ["api", "v1", "users"]}}},
        ]},
    ],
}


def _write(tmp_path):
    p = tmp_path / "acme.postman_collection.json"
    p.write_text(json.dumps(_COLLECTION))
    return str(p)


def test_parse_flattens_folders():
    reqs = {r.name: r for r in parse_collection(_COLLECTION)}
    assert set(reqs) == {"Login", "List users"}
    assert reqs["Login"].method == "POST" and reqs["Login"].path == "/api/v1/login"
    assert reqs["List users"].path == "/api/v1/users"


async def test_list_tool(tmp_path):
    out = await PostmanListTool().run({"collection_path": _write(tmp_path)})
    assert "Login: POST /api/v1/login" in out
    assert "List users: GET /api/v1/users" in out


async def test_run_uses_base_url_host_and_collection_path(tmp_path):
    calls = {}

    def fake_send(method, url, headers, body, timeout):
        calls.update(method=method, url=url, headers=headers, body=body)
        return 200, '{"ok":true}'

    tool = PostmanRunTool(send_fn=fake_send)
    out = await tool.run({
        "collection_path": _write(tmp_path), "request_name": "login",
        "base_url": "https://app.acme.example",  # host comes from here, not the collection
    })
    assert calls["method"] == "POST"
    assert calls["url"] == "https://app.acme.example/api/v1/login"  # collection host overridden
    assert "-> 200" in out


def test_run_is_scope_sensitive_on_base_url():
    tool = PostmanRunTool()
    assert tool.scope_sensitive and tool.target_field == "base_url"
    assert tool.extract_target({"base_url": "https://app.acme.example"}) == "https://app.acme.example"
