"""Integration-style tests using the offline demo-tool."""

import os
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
    monkeypatch.setenv("PATH", os.environ.get("PATH", ""))
    return ToolManager(dry_run=False)


def test_list_contains_core_tools(mgr: ToolManager):
    ids = {row["id"] for row in mgr.list_tools()}
    assert {"demo-tool", "ngspice", "kicad", "ghdl", "verilator", "python-deps"} <= ids


def test_install_status_configure_uninstall(mgr: ToolManager):
    result = mgr.install("demo-tool", force=True)
    assert result.success is True
    assert result.version == "1.0.0"
    assert Path(result.install_path).exists()
    # Portable launchers for Windows and Unix
    assert (Path(result.install_path) / "esim-demo-tool.cmd").exists()
    assert (Path(result.install_path) / "esim-demo-tool").exists()

    status = mgr.check_version("demo-tool")
    assert status.installed is True
    assert status.version == "1.0.0"
    assert status.status == "ok"

    cfg = mgr.configure("demo-tool")
    assert cfg["success"] is True
    assert cfg["env_vars"].get("ESIM_DEMO_TOOL_HOME")

    updates = {u.tool_id: u for u in mgr.check_updates()}
    assert updates["demo-tool"].status == "up_to_date"

    removed = mgr.uninstall("demo-tool")
    assert removed.success is True


def test_dry_run_kicad_does_not_persist(tmp_path, monkeypatch):
    monkeypatch.setenv("ESIM_TM_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("ESIM_TM_LOG_DIR", str(tmp_path / "logs"))
    mgr = ToolManager(dry_run=True)
    result = mgr.install("kicad")
    assert result.tool_id == "kicad"
    assert result.message
    # Dry-run must not record a live install in state
    if result.success:
        assert str(result.method).startswith("dry-run")
    state = mgr.installer.load_state()
    assert "kicad" not in state.get("tools", {})


def test_ngspice_windows_without_matching_pm_is_honest(tmp_path, monkeypatch):
    """If only winget is present, ngspice should not pretend a winget install exists."""
    monkeypatch.setenv("ESIM_TM_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("ESIM_TM_LOG_DIR", str(tmp_path / "logs"))
    mgr = ToolManager(dry_run=True)
    # Force platform to windows with only winget
    from esim_toolmanager.core.platform_utils import PlatformInfo
    from esim_toolmanager.core.installer import ToolInstaller

    mgr.platform = PlatformInfo(
        system="windows",
        release="11",
        machine="AMD64",
        available_package_managers=["winget"],
    )
    mgr.installer = ToolInstaller(
        mgr.tools,
        dry_run=True,
        config_handler=mgr.config_handler,
        platform=mgr.platform,
    )
    result = mgr.install("ngspice")
    # No chocolatey/scoop on host: dry-run may preview choco/scoop plan, but must
    # NOT claim a winget install path for ngspice.
    if not result.already_present:
        assert "Ngspice.Ngspice" not in (result.message or "")
        assert result.method != "winget"
        assert "archive" in str(result.method)
        assert result.success is True
        assert result.message


def test_ngspice_uses_archive_even_when_chocolatey_listed(tmp_path, monkeypatch):
    """Portable archive is preferred so Windows Ngspice does not need admin."""
    monkeypatch.setenv("ESIM_TM_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("ESIM_TM_LOG_DIR", str(tmp_path / "logs"))
    mgr = ToolManager(dry_run=True)
    from esim_toolmanager.core.platform_utils import PlatformInfo
    from esim_toolmanager.core.installer import ToolInstaller

    mgr.platform = PlatformInfo(
        system="windows",
        release="11",
        machine="AMD64",
        available_package_managers=["chocolatey", "winget"],
    )
    mgr.installer = ToolInstaller(
        mgr.tools,
        dry_run=True,
        config_handler=mgr.config_handler,
        platform=mgr.platform,
    )
    result = mgr.install("ngspice")
    if not result.already_present:
        assert result.success is True
        assert "archive" in str(result.method)
        assert result.method != "chocolatey"


def test_kicad_windows_adopts_or_plans_without_force(tmp_path, monkeypatch):
    """Windows KiCad must not start winget unless --force (UAC)."""
    monkeypatch.setenv("ESIM_TM_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("ESIM_TM_LOG_DIR", str(tmp_path / "logs"))
    mgr = ToolManager(dry_run=True)
    from esim_toolmanager.core.platform_utils import PlatformInfo
    from esim_toolmanager.core.installer import ToolInstaller

    mgr.platform = PlatformInfo(
        system="windows",
        release="11",
        machine="AMD64",
        available_package_managers=["winget", "chocolatey"],
    )
    mgr.installer = ToolInstaller(
        mgr.tools,
        dry_run=True,
        config_handler=mgr.config_handler,
        platform=mgr.platform,
    )
    result = mgr.install("kicad")
    if result.already_present:
        assert result.success is True
        assert result.method == "adopt-existing"
        return
    assert result.success is False
    assert result.method == "manual"
    assert "plan kicad" in result.message
    assert "winget" not in str(result.method)


def test_kicad_windows_force_still_previews_winget(tmp_path, monkeypatch):
    monkeypatch.setenv("ESIM_TM_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("ESIM_TM_LOG_DIR", str(tmp_path / "logs"))
    mgr = ToolManager(dry_run=True)
    from esim_toolmanager.core.platform_utils import PlatformInfo
    from esim_toolmanager.core.installer import ToolInstaller

    mgr.platform = PlatformInfo(
        system="windows",
        release="11",
        machine="AMD64",
        available_package_managers=["winget"],
    )
    mgr.installer = ToolInstaller(
        mgr.tools,
        dry_run=True,
        config_handler=mgr.config_handler,
        platform=mgr.platform,
    )
    result = mgr.install("kicad", force=True)
    if not result.already_present:
        assert result.success is True
        assert "winget" in str(result.method)
        assert "--scope" in " ".join(result.command or [])


def test_force_reinstall_demo(mgr: ToolManager):
    first = mgr.install("demo-tool", force=True)
    second = mgr.install("demo-tool", force=True)
    assert first.success and second.success
    assert second.version == "1.0.0"
