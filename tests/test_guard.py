"""Tests for the emulator account safety guard (no live emulator needed).

The guard lives in app.aws.guard_emulator_account; the API lifespan and the
worker entrypoint both call it and refuse to start when it raises.
"""

import pytest

import app.aws as aws_mod
from app.aws import NotEmulatorError, guard_emulator_account


def test_guard_passes_on_emulator_account(monkeypatch):
    monkeypatch.setattr(aws_mod, "get_caller_account", lambda: "000000000000")
    monkeypatch.setenv("ALLOW_REAL_AWS", "0")
    assert guard_emulator_account() == "000000000000"


def test_guard_refuses_real_account(monkeypatch):
    monkeypatch.setattr(aws_mod, "get_caller_account", lambda: "123456789012")
    monkeypatch.setenv("ALLOW_REAL_AWS", "0")
    with pytest.raises(NotEmulatorError) as exc_info:
        guard_emulator_account()
    assert "123456789012" in str(exc_info.value)
    assert "ALLOW_REAL_AWS=1" in str(exc_info.value)


def test_guard_allows_override_with_allow_real_aws(monkeypatch):
    monkeypatch.setattr(aws_mod, "get_caller_account", lambda: "123456789012")
    monkeypatch.setenv("ALLOW_REAL_AWS", "1")
    assert guard_emulator_account() == "123456789012"


def test_api_refuses_to_start_on_wrong_account(monkeypatch):
    """The FastAPI lifespan must raise so uvicorn never serves."""
    from fastapi.testclient import TestClient

    import app.main as main_mod

    monkeypatch.setattr(main_mod, "guard_emulator_account",
                        lambda: (_ for _ in ()).throw(
                            NotEmulatorError("Refusing to run: account 123456789012")))
    with pytest.raises(NotEmulatorError):
        with TestClient(main_mod.app):
            pass  # pragma: no cover


def test_worker_refuses_to_start_on_wrong_account(monkeypatch):
    import app.worker as worker_mod

    def boom():
        raise NotEmulatorError("Refusing to run: account 123456789012")

    monkeypatch.setattr(worker_mod, "guard_emulator_account", boom)
    assert worker_mod.main(["--once"]) == 2


def test_bootstrap_refuses_to_start_on_wrong_account(monkeypatch):
    import app.bootstrap as bootstrap_mod

    def boom():
        raise NotEmulatorError("Refusing to run: account 123456789012")

    monkeypatch.setattr(bootstrap_mod, "guard_emulator_account", boom)
    assert bootstrap_mod.main() == 1
