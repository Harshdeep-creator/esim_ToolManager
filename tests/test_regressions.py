"""Regression tests for install-home, env cleanup, python-deps updates, CLI deps."""

import json
from pathlib import Path

from esim_toolmanager.cli import main as cli_main
from esim_toolmanager.core.manager import ToolManager
from esim_toolmanager.utils.paths import install_home_from_binary, normalize_install_home


def test_install_home_steps_out_of_bin():
    ngspice = Path(r"C:/Program Files/ngspice/Spice64/bin/ngspice.exe")
    assert install_home_from_binary(ngspice) == Path(r"C:/Program Files/ngspice/Spice64")
    kicad = Path(r"C:/Program Files/KiCad/8.0/bin/kicad.exe")
    assert install_home_from_binary(kicad) == Path(r"C:/Program Files/KiCad/8.0")
    demo = Path.home() / ".esim_toolmanager" / "demo-tool" / "esim-demo-tool.cmd"
    assert install_home_from_binary(demo) == demo.parent
    assert normalize_install_home(Path("/usr/bin")) == Path("/usr")


def test_uninstall_drops_unique_env_and_bridge_tools(tmp_path, monkeypatch):
    monkeypatch.setenv("ESIM_TM_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("ESIM_TM_LOG_DIR", str(tmp_path / "logs"))
    mgr = ToolManager(dry_run=False)
    assert mgr.install("demo-tool", force=True).success
    mgr.configure("demo-tool")
    env_file = mgr.config_handler.env_file
    assert "ESIM_DEMO_TOOL_HOME" in env_file.read_text(encoding="utf-8")
    bridge = json.loads(mgr.config_handler.esim_bridge.read_text(encoding="utf-8"))
    assert "demo-tool" in bridge.get("tools", {})
    assert mgr.uninstall("demo-tool").success
    env_after = env_file.read_text(encoding="utf-8") if env_file.exists() else ""
    assert "ESIM_DEMO_TOOL_HOME" not in env_after
    bridge_after = json.loads(mgr.config_handler.esim_bridge.read_text(encoding="utf-8"))
    assert "demo-tool" not in bridge_after.get("tools", {})


def test_python_deps_update_check_uses_dependency_status(tmp_path, monkeypatch):
    monkeypatch.setenv("ESIM_TM_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("ESIM_TM_LOG_DIR", str(tmp_path / "logs"))
    mgr = ToolManager(dry_run=True)
    info = mgr.updater.check_tool("python-deps", query_remote=False)
    assert info.status in ("up_to_date", "update_available", "not_installed")
    assert info.message
    # Must not probe empty binaries and pretend it is a missing CLI tool
    assert "Tool not found on PATH" not in info.message


def test_cli_deps_demo_tool_exits_zero(tmp_path, monkeypatch):
    monkeypatch.setenv("ESIM_TM_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("ESIM_TM_LOG_DIR", str(tmp_path / "logs"))
    assert cli_main(["deps", "demo-tool"]) == 0


def test_cli_gui_unavailable_exits_one_without_crash(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("ESIM_TM_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("ESIM_TM_LOG_DIR", str(tmp_path / "logs"))

    def boom(_mgr):
        raise RuntimeError(
            "Cannot open GUI (no display or Tk backend). "
            "Use the CLI instead: esim-tm --help"
        )

    monkeypatch.setattr("esim_toolmanager.gui.launch_gui", boom)
    assert cli_main(["gui"]) == 1
    err = capsys.readouterr().err
    assert "GUI unavailable" in err
    assert "esim-tm list" in err
