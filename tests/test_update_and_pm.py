"""Update flow and package-manager query tests."""

import pytest

from esim_toolmanager.core.manager import ToolManager
from esim_toolmanager.core.pm_query import query_winget_package


@pytest.fixture()
def mgr(tmp_path, monkeypatch):
    home = tmp_path / "tm_home"
    logs = tmp_path / "logs"
    home.mkdir()
    logs.mkdir()
    monkeypatch.setenv("ESIM_TM_HOME", str(home))
    monkeypatch.setenv("ESIM_TM_LOG_DIR", str(logs))
    return ToolManager(dry_run=False)


def test_demo_tool_catalog_upgrade(mgr: ToolManager):
    assert mgr.install("demo-tool", force=True).success
    mgr.tools["demo-tool"]["preferred_version"] = "1.0.1"
    detected = mgr.updater.check_tool("demo-tool", query_remote=False)
    assert detected.update_available is True
    applied = mgr.update("demo-tool")
    assert applied.new_version == "1.0.1" or applied.current_version == "1.0.1"
    assert applied.status == "up_to_date"


def test_winget_kicad_query_when_available():
    info = query_winget_package("KiCad.KiCad")
    if not info.queried:
        pytest.skip("winget not available in this environment")
    # Package exists on winget today; if catalog changes, message still required
    assert info.message
    if info.remote_version:
        assert any(ch.isdigit() for ch in info.remote_version)


def test_winget_invalid_ngspice_id_reports_missing():
    info = query_winget_package("Ngspice.Ngspice")
    if not info.queried:
        pytest.skip("winget not available in this environment")
    assert info.remote_version is None
