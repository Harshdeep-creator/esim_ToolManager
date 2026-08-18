"""Version detection and comparison utilities (Windows / Linux / macOS)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

from packaging.version import InvalidVersion, Version

from esim_toolmanager.core.platform_utils import find_executable, run_command
from esim_toolmanager.utils.logger import get_logger

logger = get_logger("version")


@dataclass
class VersionInfo:
    tool_id: str
    installed: bool
    version: Optional[str] = None
    binary_path: Optional[str] = None
    preferred_version: Optional[str] = None
    min_version: Optional[str] = None
    status: str = "not_installed"
    # not_installed | ok | outdated | incompatible | unknown | partial
    message: str = ""


def parse_version_string(text: str, regex: str) -> Optional[str]:
    """Extract a version string from command output using *regex*."""
    if not text or not regex:
        return None
    match = re.search(regex, text, flags=re.IGNORECASE | re.MULTILINE)
    if match:
        return match.group(1).strip()
    fallback = re.search(r"(\d+(?:\.\d+){0,3})", text)
    return fallback.group(1) if fallback else None


def _to_version(value: str) -> Optional[Version]:
    if not value:
        return None
    cleaned = value.strip()
    try:
        return Version(cleaned)
    except InvalidVersion:
        match = re.search(r"(\d+(?:\.\d+)*)", cleaned)
        if match:
            try:
                return Version(match.group(1))
            except InvalidVersion:
                return None
        return None


def compare_versions(current: str, target: str) -> int:
    """Return -1 if current < target, 0 if equal, 1 if current > target."""
    c = _to_version(current)
    t = _to_version(target)
    if c is None or t is None:
        # Non-semver labels (e.g. esim-2.5): exact string compare
        if current == target:
            return 0
        return -1 if current < target else 1
    if c < t:
        return -1
    if c > t:
        return 1
    return 0


def is_compatible(current: str, min_version: str) -> bool:
    return compare_versions(current, min_version) >= 0


def detect_binary_version(
    binaries: Sequence[str],
    version_args: Sequence[str],
    version_regex: str,
    *,
    extra_dirs: Optional[Sequence[str]] = None,
) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """Try each binary name across PATH + OS search dirs; return (version, path, raw)."""
    for binary in binaries:
        path = find_executable([binary], extra_dirs=extra_dirs)
        if not path:
            continue
        args = [path, *(version_args or ["--version"])]
        try:
            result = run_command(list(args), timeout=20, check=False)
            output = (result.stdout or "") + "\n" + (result.stderr or "")
            version = parse_version_string(output, version_regex)
            if not version and output.strip():
                version = parse_version_string(output, r"(\d+(?:\.\d+)*)")
            if version:
                return version, path, output.strip()
        except Exception as exc:  # noqa: BLE001
            logger.debug("Version probe failed for %s: %s", binary, exc)
    return None, None, None


def evaluate_version(
    tool_id: str,
    binaries: List[str],
    version_args: List[str],
    version_regex: str,
    preferred_version: Optional[str],
    min_version: Optional[str],
    recorded_version: Optional[str] = None,
    *,
    extra_dirs: Optional[Sequence[str]] = None,
    python_deps_ok: Optional[bool] = None,
    python_deps_partial: Optional[bool] = None,
) -> VersionInfo:
    """Probe the system and classify version status."""
    # Python meta-tool: status derived from dependency checker
    if python_deps_ok is not None:
        info = VersionInfo(
            tool_id=tool_id,
            installed=bool(python_deps_ok or python_deps_partial),
            version=preferred_version if python_deps_ok else recorded_version,
            binary_path="(python environment)",
            preferred_version=preferred_version,
            min_version=min_version,
        )
        if python_deps_ok:
            info.status = "ok"
            info.version = preferred_version
            info.message = f"Python dependencies satisfy {preferred_version}"
        elif python_deps_partial:
            info.status = "partial"
            info.version = recorded_version or "partial"
            info.message = "Some Python dependencies missing or incompatible"
        else:
            info.status = "not_installed"
            info.message = "Required Python dependencies not satisfied"
        return info

    version, path, _raw = detect_binary_version(
        binaries, version_args, version_regex, extra_dirs=extra_dirs
    )
    if version is None and recorded_version:
        version = recorded_version
        path = path or "(managed install)"

    info = VersionInfo(
        tool_id=tool_id,
        installed=version is not None,
        version=version,
        binary_path=path,
        preferred_version=preferred_version,
        min_version=min_version,
    )

    if not info.installed:
        info.status = "not_installed"
        info.message = "Tool not found on PATH or common install locations"
        return info

    if min_version and not is_compatible(version, min_version):
        info.status = "incompatible"
        info.message = f"Installed {version} is below minimum {min_version}"
        return info

    if preferred_version and compare_versions(version, preferred_version) < 0:
        info.status = "outdated"
        info.message = f"Installed {version}; preferred {preferred_version} available"
        return info

    info.status = "ok"
    info.message = f"Installed version {version} meets requirements"
    return info


def search_dirs_from_tool(tool: Dict, system: str) -> List[str]:
    """Read optional per-OS search_paths from a catalog tool entry."""
    paths = (tool.get("search_paths") or {}).get(system) or []
    return [str(p) for p in paths]
