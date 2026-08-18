"""Tests for version parsing and comparison."""

from esim_toolmanager.core.version import (
    compare_versions,
    is_compatible,
    parse_version_string,
)


def test_parse_ngspice_style():
    text = "******\n** ngspice-43 : Circuit level simulation program\n"
    regex = r"(?:ngspice|Ngspice)[^0-9]*([0-9]+(?:\.[0-9]+)*)"
    assert parse_version_string(text, regex) == "43"


def test_parse_kicad_style():
    text = "8.0.2\n"
    assert parse_version_string(text, r"([0-9]+\.[0-9]+(?:\.[0-9]+)?)") == "8.0.2"


def test_compare_versions():
    assert compare_versions("36", "43") < 0
    assert compare_versions("43", "43") == 0
    assert compare_versions("8.0.2", "8.0") > 0


def test_is_compatible():
    assert is_compatible("43", "36")
    assert not is_compatible("30", "36")
