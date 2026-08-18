"""Dependency checking for system binaries, Python packages, and host readiness."""

from __future__ import annotations

import importlib.metadata
import importlib.util
import sys
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from packaging.requirements import Requirement
from packaging.version import InvalidVersion, Version

from esim_toolmanager.core.platform_utils import (
    command_exists,
    find_executable,
    normalize_system,
    python_executable,
)
from esim_toolmanager.utils.logger import get_logger

logger = get_logger("dependency")


@dataclass
class DependencyResult:
    name: str
    kind: str  # system | python | platform | tool_binary
    satisfied: bool
    installed_version: Optional[str] = None
    required: Optional[str] = None
    message: str = ""
    remediation: str = ""


@dataclass
class DependencyReport:
    tool_id: str
    results: List[DependencyResult] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(r.satisfied for r in self.results)

    @property
    def partial(self) -> bool:
        if not self.results:
            return False
        sat = sum(1 for r in self.results if r.satisfied)
        return 0 < sat < len(self.results)

    def missing(self) -> List[DependencyResult]:
        return [r for r in self.results if not r.satisfied]


def _get_python_version(dist_name: str) -> Optional[str]:
    """Resolve installed distribution version (handles import vs dist names)."""
    aliases = {
        "pillow": "Pillow",
        "Pillow": "Pillow",
        "pyqt6": "PyQt6",
        "PyQt6": "PyQt6",
    }
    candidates = [dist_name]
    if dist_name in aliases:
        candidates.append(aliases[dist_name])
    lower_map = {k.lower(): v for k, v in aliases.items()}
    if dist_name.lower() in lower_map:
        candidates.append(lower_map[dist_name.lower()])

    for name in candidates:
        try:
            return importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            continue

    module_name = dist_name.replace("-", "_")
    if importlib.util.find_spec(module_name) is not None:
        return "unknown"
    return None


def python_requirements_for_host(deps: Optional[Dict] = None) -> Tuple[List[str], str]:
    """Pick installable requirement specs for the current interpreter.

    eSim 2.5 official pins (numpy==1.24.4, scipy==1.10.1, matplotlib==3.7.5)
    have no wheels on Python 3.12+. When ``python_compat`` is declared, use
    that list on 3.12+ so install/deps report real missing packages instead of
    an unfixable platform failure.
    """
    deps = deps or {}
    official = [str(s) for s in (deps.get("python") or [])]
    compat = [str(s) for s in (deps.get("python_compat") or [])]
    if sys.version_info >= (3, 12) and compat:
        return compat, "python3.12+"
    return official, "esim-2.5"


def check_python_requirement(spec: str) -> DependencyResult:
    """Check a PEP 508 requirement string such as 'numpy==1.24.4'."""
    try:
        req = Requirement(spec)
    except Exception as exc:  # noqa: BLE001
        return DependencyResult(
            name=spec,
            kind="python",
            satisfied=False,
            required=spec,
            message=f"Invalid requirement: {exc}",
            remediation="Fix the requirement string in config/tools.yaml",
        )

    installed = _get_python_version(req.name)
    if installed is None:
        return DependencyResult(
            name=req.name,
            kind="python",
            satisfied=False,
            required=spec,
            message=f"Missing Python package: {req.name}",
            remediation=f'python -m pip install "{spec}"',
        )

    if installed == "unknown":
        if req.specifier:
            return DependencyResult(
                name=req.name,
                kind="python",
                satisfied=False,
                installed_version=installed,
                required=spec,
                message="Package importable but version metadata unavailable; cannot verify pin",
                remediation=f'python -m pip install --force-reinstall "{spec}"',
            )
        return DependencyResult(
            name=req.name,
            kind="python",
            satisfied=True,
            installed_version=installed,
            required=spec,
            message="Package importable (version metadata unavailable)",
        )

    try:
        if req.specifier:
            ok = Version(installed) in req.specifier
        else:
            ok = True
    except InvalidVersion:
        ok = str(installed) in str(req.specifier) if req.specifier else True

    return DependencyResult(
        name=req.name,
        kind="python",
        satisfied=ok,
        installed_version=installed,
        required=spec,
        message=(
            f"OK ({installed})"
            if ok
            else f"Incompatible: installed {installed}, required {spec}"
        ),
        remediation=("" if ok else f'python -m pip install "{spec}"'),
    )


def check_system_binary(name: str) -> DependencyResult:
    path = find_executable([name])
    exists = path is not None
    return DependencyResult(
        name=name,
        kind="system",
        satisfied=exists,
        message=(f"Found on PATH: {path}" if exists else f"Missing system dependency: {name}"),
        remediation=("" if exists else f"Install '{name}' using your OS package manager"),
    )


def check_tool_binary(name: str) -> DependencyResult:
    path = find_executable([name])
    return DependencyResult(
        name=name,
        kind="tool_binary",
        satisfied=path is not None,
        message=(f"Binary available: {path}" if path else f"Tool binary not found: {name}"),
        remediation=("" if path else f"Run: esim-tm install <tool>  (needs binary '{name}')"),
    )


def check_host_platform() -> DependencyReport:
    """Baseline host checks that apply on Windows, Linux, and macOS."""
    report = DependencyReport(tool_id="host")
    system = normalize_system()
    report.results.append(
        DependencyResult(
            name="os",
            kind="platform",
            satisfied=system in ("windows", "linux", "darwin"),
            installed_version=system,
            message=f"Detected OS family: {system}",
            remediation="Supported OS families: windows, linux, darwin",
        )
    )
    py = python_executable()
    report.results.append(
        DependencyResult(
            name="python",
            kind="platform",
            satisfied=sys.version_info >= (3, 9),
            installed_version=platform_python_version(),
            required=">=3.9",
            message=f"Interpreter: {py}",
            remediation="Install Python 3.9+ from https://www.python.org/downloads/",
        )
    )
    pip_ok = command_exists("pip") or command_exists("pip3")
    # pip via python -m pip is enough
    try:
        from esim_toolmanager.core.platform_utils import run_command

        r = run_command([py, "-m", "pip", "--version"], timeout=20)
        pip_ok = r.returncode == 0
    except Exception:  # noqa: BLE001
        pass
    report.results.append(
        DependencyResult(
            name="pip",
            kind="platform",
            satisfied=pip_ok,
            message="python -m pip available" if pip_ok else "pip not available",
            remediation="python -m ensurepip --upgrade",
        )
    )
    return report


def platform_python_version() -> str:
    return f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"


def check_tool_dependencies(
    tool_id: str,
    deps: Dict[str, List[str]],
    *,
    binaries: Optional[Sequence[str]] = None,
    check_binaries: bool = False,
) -> DependencyReport:
    """Evaluate system + python dependencies declared for a tool."""
    report = DependencyReport(tool_id=tool_id)
    for binary in deps.get("system", []) or []:
        report.results.append(check_system_binary(binary))
    specs, profile = python_requirements_for_host(deps)
    if profile != "esim-2.5" and specs:
        report.results.append(
            DependencyResult(
                name="python-stack-profile",
                kind="platform",
                satisfied=True,
                installed_version=platform_python_version(),
                required=profile,
                message=(
                    f"Python {platform_python_version()} cannot install eSim 2.5 "
                    "pins (numpy==1.24.4, scipy==1.10.1 have no 3.12 wheels); "
                    f"checking {profile} compatible specs instead."
                ),
                remediation="For a bit-exact eSim 2.5 stack, use Python 3.10 or 3.11",
            )
        )
    for spec in specs:
        report.results.append(check_python_requirement(spec))
    if check_binaries and binaries:
        for binary in binaries:
            report.results.append(check_tool_binary(binary))
    logger.info(
        "Dependency check for %s: %s/%s satisfied",
        tool_id,
        sum(1 for r in report.results if r.satisfied),
        len(report.results),
    )
    return report


def summarize_reports(reports: List[DependencyReport]) -> str:
    lines = []
    for report in reports:
        if not report.results:
            lines.append(f"[OK] {report.tool_id} (no dependencies declared)")
            continue
        status = "OK" if report.ok else ("PARTIAL" if report.partial else "ISSUES")
        lines.append(f"[{status}] {report.tool_id}")
        for r in report.results:
            mark = "[OK]" if r.satisfied else "[X]"
            ver = f" ({r.installed_version})" if r.installed_version else ""
            lines.append(f"  {mark} [{r.kind}] {r.name}{ver} - {r.message}")
            if not r.satisfied and r.remediation:
                lines.append(f"       fix: {r.remediation}")
    return "\n".join(lines) if lines else "No dependencies declared."
