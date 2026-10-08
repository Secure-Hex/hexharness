"""Update check: version comparison, env disable, and fail-safe offline behavior."""
from __future__ import annotations

import hexharness.update as upd


def test_version_compare(monkeypatch):
    monkeypatch.delenv("HEXHARNESS_NO_UPDATE_CHECK", raising=False)
    monkeypatch.setattr(upd, "current_version", lambda: "1.0.1")
    monkeypatch.setattr(upd, "latest_version", lambda **_: "1.2.0")
    assert upd.check_update() == ("1.0.1", "1.2.0")

    monkeypatch.setattr(upd, "latest_version", lambda **_: "1.0.1")  # same => no update
    assert upd.check_update() is None

    monkeypatch.setattr(upd, "latest_version", lambda **_: "1.0.0")  # older on PyPI => no update
    assert upd.check_update() is None


def test_numeric_not_lexical(monkeypatch):
    # 1.10.0 must be newer than 1.9.0 (lexical compare would get this wrong)
    monkeypatch.delenv("HEXHARNESS_NO_UPDATE_CHECK", raising=False)
    monkeypatch.setattr(upd, "current_version", lambda: "1.9.0")
    monkeypatch.setattr(upd, "latest_version", lambda **_: "1.10.0")
    assert upd.check_update() == ("1.9.0", "1.10.0")


def test_env_disables_check(monkeypatch):
    monkeypatch.setenv("HEXHARNESS_NO_UPDATE_CHECK", "1")
    monkeypatch.setattr(upd, "current_version", lambda: "1.0.0")
    monkeypatch.setattr(upd, "latest_version", lambda **_: "2.0.0")
    assert upd.check_update() is None


def test_offline_is_fail_safe(monkeypatch):
    monkeypatch.setattr(upd, "current_version", lambda: "1.0.0")
    monkeypatch.setattr(upd, "latest_version", lambda **_: None)  # fetch failed
    assert upd.check_update() is None
