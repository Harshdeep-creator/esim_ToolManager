"""Tests for dependency checking helpers."""

import sys
from pathlib import Path

from esim_toolmanager.core.dependency import (
    check_python_requirement,
    check_system_binary,
    python_requirements_for_host,
)


def test_python_packaging_present():
    result = check_python_requirement("packaging>=23.0")
    assert result.satisfied is True
    assert result.kind == "python"


def test_missing_python_package():
    result = check_python_requirement("definitely_not_a_real_pkg_xyz_12345==1.0.0")
    assert result.satisfied is False


def test_system_python_binary():
    exe_name = Path(sys.executable).name
    result = check_system_binary(exe_name)
    if not result.satisfied:
        result = check_system_binary("python")
    assert result.kind == "system"
    assert result.satisfied is True


def test_python_requirements_for_host_picks_compat_on_312():
    deps = {
        "python": ["numpy==1.24.4"],
        "python_compat": ["numpy>=1.26.0"],
    }
    specs, profile = python_requirements_for_host(deps)
    if sys.version_info >= (3, 12):
        assert specs == ["numpy>=1.26.0"]
        assert profile == "python3.12+"
    else:
        assert specs == ["numpy==1.24.4"]
        assert profile == "esim-2.5"
