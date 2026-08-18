"""Configuration + end-to-end verify tests."""

from pathlib import Path

import pytest

from esim_toolmanager.core.manager import ToolManager


@pytest.fixture()
def mgr(tmp_path, monkeypatch):
    home = tmp_path / "tm_home"
    logs = tmp_path / "logs"
    home.mkdir()
    logs.mkdir()
    monkeypatch.setenv("ESIM_TM_HOME", str(home))
    monkeypatch.setenv("ESIM_TM_LOG_DIR", str(logs))
    return ToolManager(dry_run=False)


def test_configure_writes_all_activation_scripts(mgr: ToolManager):
    mgr.install("demo-tool", force=True)
    result = mgr.configure("demo-tool")
    assert result["success"] is True
    cfg = Path(mgr.config_handler.config_dir)
    for name in ("activate.sh", "activate.ps1", "activate.bat", "esim_bridge.json"):
        assert (cfg / name).exists(), name
    bridge = (cfg / "esim_bridge.json").read_text(encoding="utf-8")
    assert "windows" in bridge and "linux" in bridge and "darwin" in bridge


def test_verify_passes(mgr: ToolManager):
    report = mgr.verify()
    assert report["overall_ok"] is True
    assert all(step["ok"] for step in report["steps"])


def test_host_deps_included(mgr: ToolManager):
    reports = mgr.check_dependencies("demo-tool")
    assert reports[0].tool_id == "host"
    assert any(r.name == "python" for r in reports[0].results)


def test_update_idempotent_when_current(mgr: ToolManager):
    mgr.install("demo-tool", force=True)
    info = mgr.update("demo-tool")
    assert info.status == "up_to_date"
