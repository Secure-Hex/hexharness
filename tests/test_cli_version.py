import pytest

from hexharness.__main__ import _parser, _version


def test_version_returns_str():
    assert isinstance(_version(), str) and _version()


def test_version_flag_prints_and_exits():
    # action="version" prints to stdout and raises SystemExit(0).
    with pytest.raises(SystemExit) as exc:
        _parser().parse_args(["--version"])
    assert exc.value.code == 0


def test_version_not_swallowed_by_run_shim(monkeypatch):
    # main()'s back-compat shim prepends "run" for a bare prompt; --version must pass
    # through to the top-level parser and exit 0, not hit the run subparser (exit 2).
    from hexharness import __main__

    monkeypatch.setattr(__main__.sys, "argv", ["hexharness", "--version"])
    with pytest.raises(SystemExit) as exc:
        __main__.main()
    assert exc.value.code == 0
