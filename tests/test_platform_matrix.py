"""Cross-platform install plan and package-manager command tests."""

from esim_toolmanager.core.platform_utils import (
    build_pm_command,
    install_plan_matrix,
    normalize_system,
)


def test_normalize_system_families():
    assert normalize_system("Windows") == "windows"
    assert normalize_system("Linux") == "linux"
    assert normalize_system("Darwin") == "darwin"


def test_build_pm_commands_cover_major_managers():
    assert build_pm_command("apt", ["ngspice"])[0:3] == ["sudo", "apt-get", "install"]
    assert "ngspice" in build_pm_command("brew", ["ngspice"])
    assert "--id" in build_pm_command("winget", ["Ngspice.Ngspice"])
    assert build_pm_command("chocolatey", ["ngspice"])[0] == "choco"
    assert build_pm_command("dnf", ["kicad"])[1] == "dnf"
    assert build_pm_command("pacman", ["ghdl"])[1] == "pacman"


def test_ngspice_plan_has_windows_linux_darwin(tmp_path, monkeypatch):
    from esim_toolmanager.core.manager import ToolManager

    monkeypatch.setenv("ESIM_TM_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("ESIM_TM_LOG_DIR", str(tmp_path / "logs"))
    mgr = ToolManager(dry_run=True)
    plan = mgr.plan("ngspice")[0]
    matrix = plan["matrix"]
    assert set(matrix.keys()) >= {"windows", "linux", "darwin"}
    # Ngspice is not on winget; Windows catalog uses chocolatey/scoop
    assert "chocolatey" in matrix["windows"] or "scoop" in matrix["windows"]
    assert "portable_archive" in matrix["windows"]
    assert "apt" in matrix["linux"] or "dnf" in matrix["linux"]
    assert "brew" in matrix["darwin"]
    # KiCad remains available via winget on Windows
    kicad = mgr.plan("kicad")[0]["matrix"]
    assert "winget" in kicad["windows"]
    assert "brew" in kicad["darwin"]


def test_install_plan_matrix_local_bundle():
    tool = {
        "display_name": "Demo",
        "download": {"local_bundle": True},
        "packages": {"windows": {}, "linux": {}, "darwin": {}},
    }
    matrix = install_plan_matrix(tool)
    for os_name in ("windows", "linux", "darwin"):
        assert "local_bundle" in matrix[os_name]
