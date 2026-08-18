"""Query package managers for available / installed package versions.

Used by the update system. Does not modify configuration or dependency modules.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional

from esim_toolmanager.core.platform_utils import (
    PlatformInfo,
    catalog_pm_key,
    command_exists,
    run_command,
)
from esim_toolmanager.utils.logger import get_logger

logger = get_logger("pm_query")


@dataclass
class RemoteVersionInfo:
    tool_id: str
    package_manager: str
    package_id: str
    remote_version: Optional[str]
    queried: bool
    message: str


def _parse_winget_version(text: str) -> Optional[str]:
    match = re.search(r"(?im)^\s*Version:\s*([^\r\n]+)\s*$", text or "")
    if match:
        return match.group(1).strip()
    return None


def query_winget_package(package_id: str) -> RemoteVersionInfo:
    if not command_exists("winget"):
        return RemoteVersionInfo(
            tool_id="",
            package_manager="winget",
            package_id=package_id,
            remote_version=None,
            queried=False,
            message="winget not available",
        )
    try:
        result = run_command(
            ["winget", "show", "--id", package_id, "-e"],
            timeout=20,
            check=False,
        )
        output = (result.stdout or "") + "\n" + (result.stderr or "")
        if result.returncode != 0 or "No package found" in output:
            return RemoteVersionInfo(
                tool_id="",
                package_manager="winget",
                package_id=package_id,
                remote_version=None,
                queried=True,
                message=f"Package not found on winget: {package_id}",
            )
        version = _parse_winget_version(output)
        return RemoteVersionInfo(
            tool_id="",
            package_manager="winget",
            package_id=package_id,
            remote_version=version,
            queried=True,
            message=(
                f"winget reports {package_id} @ {version}"
                if version
                else f"winget found {package_id} (version unknown)"
            ),
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("winget query failed: %s", exc)
        return RemoteVersionInfo(
            tool_id="",
            package_manager="winget",
            package_id=package_id,
            remote_version=None,
            queried=False,
            message=str(exc),
        )


def query_brew_package(package_name: str) -> RemoteVersionInfo:
    brew = "brew"
    if not command_exists(brew):
        return RemoteVersionInfo(
            tool_id="",
            package_manager="brew",
            package_id=package_name,
            remote_version=None,
            queried=False,
            message="brew not available",
        )
    # Strip cask flag tokens
    name = package_name
    try:
        result = run_command(["brew", "info", "--json=v2", name], timeout=20, check=False)
        if result.returncode != 0:
            # fallback plain info
            result = run_command(["brew", "info", name], timeout=20, check=False)
            output = (result.stdout or "") + "\n" + (result.stderr or "")
            match = re.search(r"stable\s+([0-9][^\s,]+)", output, re.I)
            version = match.group(1) if match else None
        else:
            import json

            data = json.loads(result.stdout or "{}")
            formulae = data.get("formulae") or []
            casks = data.get("casks") or []
            version = None
            if formulae:
                version = (formulae[0].get("versions") or {}).get("stable")
            elif casks:
                version = casks[0].get("version")
        return RemoteVersionInfo(
            tool_id="",
            package_manager="brew",
            package_id=name,
            remote_version=version,
            queried=True,
            message=f"brew reports {name} @ {version}" if version else f"brew lookup for {name}",
        )
    except Exception as exc:  # noqa: BLE001
        return RemoteVersionInfo(
            tool_id="",
            package_manager="brew",
            package_id=name,
            remote_version=None,
            queried=False,
            message=str(exc),
        )


def query_apt_package(package_name: str) -> RemoteVersionInfo:
    if not command_exists("apt-cache"):
        return RemoteVersionInfo(
            tool_id="",
            package_manager="apt",
            package_id=package_name,
            remote_version=None,
            queried=False,
            message="apt-cache not available",
        )
    try:
        result = run_command(
            ["apt-cache", "policy", package_name], timeout=30, check=False
        )
        output = result.stdout or ""
        match = re.search(r"Candidate:\s*(\S+)", output)
        version = match.group(1) if match else None
        if version == "(none)":
            version = None
        return RemoteVersionInfo(
            tool_id="",
            package_manager="apt",
            package_id=package_name,
            remote_version=version,
            queried=True,
            message=(
                f"apt candidate {package_name} @ {version}"
                if version
                else f"No apt candidate for {package_name}"
            ),
        )
    except Exception as exc:  # noqa: BLE001
        return RemoteVersionInfo(
            tool_id="",
            package_manager="apt",
            package_id=package_name,
            remote_version=None,
            queried=False,
            message=str(exc),
        )


def query_choco_package(package_name: str) -> RemoteVersionInfo:
    if not command_exists("choco"):
        return RemoteVersionInfo(
            tool_id="",
            package_manager="chocolatey",
            package_id=package_name,
            remote_version=None,
            queried=False,
            message="choco not available",
        )
    try:
        result = run_command(
            ["choco", "search", package_name, "--exact", "--limit-output"],
            timeout=45,
            check=False,
        )
        output = (result.stdout or "").strip()
        version = None
        if output and "|" in output:
            version = output.split("|", 1)[1].strip() or None
        return RemoteVersionInfo(
            tool_id="",
            package_manager="chocolatey",
            package_id=package_name,
            remote_version=version,
            queried=True,
            message=(
                f"choco reports {package_name} @ {version}"
                if version
                else f"No exact choco match for {package_name}"
            ),
        )
    except Exception as exc:  # noqa: BLE001
        return RemoteVersionInfo(
            tool_id="",
            package_manager="chocolatey",
            package_id=package_name,
            remote_version=None,
            queried=False,
            message=str(exc),
        )


def query_scoop_package(package_name: str) -> RemoteVersionInfo:
    if not command_exists("scoop"):
        return RemoteVersionInfo(
            tool_id="",
            package_manager="scoop",
            package_id=package_name,
            remote_version=None,
            queried=False,
            message="scoop not available",
        )
    try:
        result = run_command(["scoop", "info", package_name], timeout=45, check=False)
        output = (result.stdout or "") + "\n" + (result.stderr or "")
        match = re.search(r"(?im)^\s*Version:\s*(\S+)", output)
        version = match.group(1) if match else None
        return RemoteVersionInfo(
            tool_id="",
            package_manager="scoop",
            package_id=package_name,
            remote_version=version,
            queried=True,
            message=(
                f"scoop reports {package_name} @ {version}"
                if version
                else f"scoop info for {package_name} (version unknown)"
            ),
        )
    except Exception as exc:  # noqa: BLE001
        return RemoteVersionInfo(
            tool_id="",
            package_manager="scoop",
            package_id=package_name,
            remote_version=None,
            queried=False,
            message=str(exc),
        )


def query_remote_for_tool(
    tool_id: str,
    tool: dict,
    platform: PlatformInfo,
) -> List[RemoteVersionInfo]:
    """Query available remote versions using PMs present on this host."""
    results: List[RemoteVersionInfo] = []
    packages = (tool.get("packages") or {}).get(platform.system) or {}
    for pm in platform.available_package_managers:
        key = catalog_pm_key(pm)
        pkg_list = packages.get(key) or []
        # Filter flag-only tokens for brew
        pkg_names = [p for p in pkg_list if not str(p).startswith("-")]
        if not pkg_names:
            continue
        package_id = pkg_names[0]
        if key == "winget":
            info = query_winget_package(package_id)
        elif key == "brew":
            info = query_brew_package(package_id)
        elif key == "apt":
            info = query_apt_package(package_id)
        elif key == "chocolatey":
            info = query_choco_package(package_id)
        elif key == "scoop":
            info = query_scoop_package(package_id)
        else:
            info = RemoteVersionInfo(
                tool_id=tool_id,
                package_manager=key,
                package_id=package_id,
                remote_version=None,
                queried=False,
                message=f"Remote query not implemented for {key} (catalog preferred still used)",
            )
        info.tool_id = tool_id
        results.append(info)
    return results
