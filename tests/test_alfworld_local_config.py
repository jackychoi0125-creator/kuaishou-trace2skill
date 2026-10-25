"""The submitted Round 2 launcher works without the author's model.txt."""
from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(SCRIPTS.parent / "src"))

import run_alfworld_evolution as launcher  # noqa: E402


def test_explicit_runtime_settings_work_without_model_file(monkeypatch, tmp_path):
    monkeypatch.setattr(launcher, "WORKSPACE", tmp_path)
    monkeypatch.setattr(launcher, "KIT", tmp_path / "kit")
    monkeypatch.setenv("TRACE2SKILL_LOCAL_API_KEY", "test-token")
    monkeypatch.setenv("TRACE2SKILL_LOCAL_BASE_URL", "https://example.test/endpoint")
    key, base, ids = launcher.load_local_config()
    assert key == "test-token"
    assert base == "https://example.test/endpoint"
    assert ids == launcher.yaml_models()


def test_private_kit_env_is_a_portable_fallback(monkeypatch, tmp_path):
    monkeypatch.setattr(launcher, "WORKSPACE", tmp_path)
    kit = tmp_path / "kit"
    kit.mkdir()
    (kit / "kit.env").write_text("API_KEY='test-token'\nKIT_BASE_URL='https://example.test/endpoint'\n")
    monkeypatch.setattr(launcher, "KIT", kit)
    monkeypatch.delenv("TRACE2SKILL_LOCAL_API_KEY", raising=False)
    monkeypatch.delenv("TRACE2SKILL_LOCAL_BASE_URL", raising=False)
    key, base, ids = launcher.load_local_config()
    assert key == "test-token"
    assert base == "https://example.test/endpoint"
    assert ids == launcher.yaml_models()
