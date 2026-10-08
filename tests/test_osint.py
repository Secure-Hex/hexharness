"""OSINT tools with injected fakes — no real network, no docker."""
from __future__ import annotations

import json

from hexharness.tools.base import RiskLevel
from hexharness.tools.native.osint import (
    CloudStorageEnumTool,
    GithubDorkTool,
    WaybackUrlsTool,
)


class FakeVault:
    def __init__(self, **secrets):
        self._s = secrets

    def get(self, name):
        return self._s.get(name)


# --- Wayback (fetch_fn injected) ---

async def test_wayback_parses_and_dedupes():
    captured = {}

    def fake_fetch(url):
        captured["url"] = url
        return json.dumps([["original"],
                           ["http://securehex.cl/a"],
                           ["http://securehex.cl/b"],
                           ["http://securehex.cl/a"]])  # dupe

    out = await WaybackUrlsTool(fetch_fn=fake_fetch).run({"domain": "securehex.cl", "limit": 5})
    assert "http://securehex.cl/a" in out and "http://securehex.cl/b" in out
    assert out.count("http://securehex.cl/a") == 1  # deduped
    assert "securehex.cl%2F%2A" in captured["url"] and "limit=5" in captured["url"]  # url-encoded /*


def test_wayback_fields():
    t = WaybackUrlsTool()
    assert t.scope_sensitive and t.target_field == "domain"
    assert t.risk_level is RiskLevel.PASSIVE and not t.requires_approval


async def test_wayback_handles_fetch_error():
    def boom(url):
        raise TimeoutError("slow")

    out = await WaybackUrlsTool(fetch_fn=boom).run({"domain": "x.cl"})
    assert "wayback failed" in out


# --- GithubDork (fake vault + fetch_fn injected) ---

async def test_github_dork_builds_authed_request_and_parses():
    seen = {}

    def fake_fetch(url, token):
        seen["url"] = url
        seen["token"] = token
        return json.dumps({"total_count": 1, "items": [
            {"repository": {"full_name": "acme/app"}, "path": "config/secrets.yml",
             "html_url": "https://github.com/acme/app/blob/main/config/secrets.yml"}]})

    tool = GithubDorkTool(FakeVault(GITHUB_TOKEN="ghp_test"), fetch_fn=fake_fetch)
    out = await tool.run({"query": "org:acme AWS_SECRET", "per_page": 10})
    assert seen["token"] == "ghp_test"  # read from the vault, passed to the fetcher
    assert "per_page=10" in seen["url"] and "AWS_SECRET" in seen["url"]
    assert "acme/app" in out and "config/secrets.yml" in out


def test_github_dork_fields():
    t = GithubDorkTool(FakeVault())
    assert t.required_secrets == ["GITHUB_TOKEN"]
    assert not t.scope_sensitive and t.risk_level is RiskLevel.PASSIVE


async def test_github_dork_no_matches():
    tool = GithubDorkTool(FakeVault(GITHUB_TOKEN="t"),
                          fetch_fn=lambda url, token: json.dumps({"total_count": 0, "items": []}))
    out = await tool.run({"query": "nope"})
    assert "no code matches" in out


# --- CloudStorageEnum (http_fn injected) ---

async def test_cloud_storage_reports_public_vs_private():
    def fake_http(url):
        if url.startswith("https://acme.s3"):
            return 200, "<ListBucketResult>"       # public
        if "blob.core.windows.net" in url:
            return 403, "AuthenticationFailed"      # exists, private
        return 404, "NoSuchBucket"                   # absent

    out = await CloudStorageEnumTool(http_fn=fake_http).run({"name": "acme"})
    assert "[PUB " in out and "acme.s3.amazonaws.com" in out
    assert "[priv]" in out
    assert "[none]" in out


def test_cloud_storage_fields():
    t = CloudStorageEnumTool()
    assert t.requires_approval and t.risk_level is RiskLevel.ACTIVE and not t.scope_sensitive


async def test_cloud_storage_catches_per_candidate_error():
    def flaky(url):
        if "s3" in url:
            raise ConnectionError("refused")
        return 404, ""

    out = await CloudStorageEnumTool(http_fn=flaky).run({"name": "x"})
    assert "[err ]" in out and "ConnectionError" in out  # did not crash the turn
