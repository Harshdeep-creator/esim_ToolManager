"""python-deps version_source and dependency remediation tests."""

import pytest

from esim_toolmanager.core.dependency import check_python_requirement
from esim_toolmanager.core.manager import ToolManager


def test_python_deps_status_uses_dependency_checker(tmp_path, monkeypatch):
    monkeypatch.setenv("ESIM_TM_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("ESIM_TM_LOG_DIR", str(tmp_path / "logs"))
    mgr = ToolManager(dry_run=True)
    info = mgr.check_version("python-deps")
    assert info.status in ("ok", "partial", "not_installed")
    assert info.binary_path == "(python environment)"


def test_missing_package_has_remediation():
    result = check_python_requirement("definitely_missing_pkg_abc_999==1.0.0")
    assert result.satisfied is False
    assert "pip install" in result.remediation


def test_python_deps_312_profile_note_is_satisfied_not_a_host_failure(
    tmp_path, monkeypatch
):
    import sys

    if sys.version_info < (3, 12):
        pytest.skip("compat profile note only applies on Python 3.12+")

    monkeypatch.setenv("ESIM_TM_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("ESIM_TM_LOG_DIR", str(tmp_path / "logs"))
    mgr = ToolManager(dry_run=True)
    reports = mgr.check_dependencies("python-deps")
    py = next(r for r in reports if r.tool_id == "python-deps")
    notes = [x for x in py.results if x.name == "python-stack-profile"]
    assert notes and notes[0].satisfied is True
    assert not any(x.name == "python-runtime" and not x.satisfied for x in py.results)
    required = [x.required for x in py.results if x.kind == "python"]
    assert "numpy==1.24.4" not in required
    assert any(r and "numpy>=1.26" in r for r in required)


def test_python_deps_dry_run_install_uses_compat_pins(tmp_path, monkeypatch):
    import sys

    if sys.version_info < (3, 12):
        pytest.skip("compat install path only on Python 3.12+")

    monkeypatch.setenv("ESIM_TM_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("ESIM_TM_LOG_DIR", str(tmp_path / "logs"))
    mgr = ToolManager(dry_run=True)
    result = mgr.install("python-deps")
    assert result.success is True
    joined = " ".join(result.command or [])
    assert "numpy==1.24.4" not in joined
    assert "numpy>=1.26.0" in joined
