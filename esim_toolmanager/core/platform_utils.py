"""OS detection, package-manager discovery, and cross-platform path search."""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence

from esim_toolmanager.utils.logger import get_logger

logger = get_logger("platform")


@dataclass
class PlatformInfo:
    system: str  # windows | linux | darwin
    release: str
    machine: str
    is_admin_hint: bool = False
    available_package_managers: List[str] = field(default_factory=list)
    python_executable: str = field(default_factory=lambda: sys.executable)


def normalize_system(name: Optional[str] = None) -> str:
    """Map platform.system() to catalog keys used in tools.yaml."""
    raw = (name or platform.system()).lower()
    if raw.startswith("win"):
        return "windows"
    if raw == "darwin":
        return "darwin"
    if raw.startswith("linux"):
        return "linux"
    return raw


def python_executable() -> str:
    """Return the current interpreter path (cross-platform)."""
    return sys.executable


def which(cmd: str) -> Optional[str]:
    """Locate an executable on PATH (handles Windows PATHEXT)."""
    return shutil.which(cmd)


def command_exists(cmd: str) -> bool:
    return which(cmd) is not None


def run_command(
    args: List[str],
    *,
    timeout: int = 120,
    check: bool = False,
    capture: bool = True,
    env: Optional[dict] = None,
) -> subprocess.CompletedProcess:
    """Run a subprocess safely with logging (no shell interpolation)."""
    logger.debug("Running command: %s", " ".join(str(a) for a in args))
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    return subprocess.run(
        args,
        timeout=timeout,
        check=check,
        capture_output=capture,
        text=True,
        env=merged_env,
        shell=False,
    )


def _homebrew_prefixes() -> List[Path]:
    prefixes: List[Path] = []
    for candidate in ("/opt/homebrew", "/usr/local"):
        p = Path(candidate)
        if (p / "bin").is_dir():
            prefixes.append(p)
    brew = which("brew")
    if brew:
        try:
            result = run_command(["brew", "--prefix"], timeout=10)
            if result.returncode == 0 and result.stdout.strip():
                prefixes.insert(0, Path(result.stdout.strip()))
        except Exception:  # noqa: BLE001
            pass
    # dedupe
    seen = set()
    out: List[Path] = []
    for p in prefixes:
        key = str(p.resolve()) if p.exists() else str(p)
        if key not in seen:
            seen.add(key)
            out.append(p)
    return out


def default_search_dirs(system: Optional[str] = None) -> List[Path]:
    """Common install locations for EDA tools on each OS."""
    system = normalize_system(system)
    dirs: List[Path] = []
    home = Path.home()

    if system == "windows":
        pf = os.environ.get("ProgramFiles", r"C:\Program Files")
        pf86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
        local = os.environ.get("LOCALAPPDATA", str(home / "AppData" / "Local"))
        dirs.extend(
            [
                Path(pf) / "Ngspice" / "bin",
                Path(pf) / "ngspice" / "bin",
                Path(pf) / "KiCad",
                Path(pf) / "KiCad" / "8.0" / "bin",
                Path(pf) / "KiCad" / "7.0" / "bin",
                Path(pf) / "KiCad" / "9.0" / "bin",
                Path(pf86) / "KiCad" / "8.0" / "bin",
                Path(local) / "Programs",
                home / ".esim_toolmanager",
            ]
        )
        # Expand KiCad versioned bin folders if present
        for base in (Path(pf) / "KiCad", Path(pf86) / "KiCad"):
            if base.is_dir():
                for child in base.iterdir():
                    bin_dir = child / "bin"
                    if bin_dir.is_dir():
                        dirs.append(bin_dir)
    elif system == "darwin":
        for prefix in _homebrew_prefixes():
            dirs.extend([prefix / "bin", prefix / "sbin"])
        dirs.extend(
            [
                Path("/Applications/KiCad/KiCad.app/Contents/MacOS"),
                Path("/Applications/KiCad.app/Contents/MacOS"),
                home / "Applications" / "KiCad" / "KiCad.app" / "Contents" / "MacOS",
                home / ".esim_toolmanager",
            ]
        )
    else:  # linux and others
        dirs.extend(
            [
                Path("/usr/bin"),
                Path("/usr/local/bin"),
                Path("/bin"),
                Path("/snap/bin"),
                Path("/var/lib/flatpak/exports/bin"),
                home / ".local" / "bin",
                home / ".esim_toolmanager",
            ]
        )
    return dirs


def find_executable(
    names: Sequence[str],
    *,
    extra_dirs: Optional[Iterable[str]] = None,
    system: Optional[str] = None,
) -> Optional[str]:
    """
    Locate an executable by name on PATH and OS-specific common directories.

    Works the same way on Windows, Linux, and macOS — never assumes one OS.
    """
    search_names: List[str] = []
    for name in names:
        if not name:
            continue
        search_names.append(name)
        system_n = normalize_system(system)
        if system_n == "windows":
            stem = Path(name).stem
            for ext in ("", ".exe", ".cmd", ".bat", ".COM"):
                candidate = stem + ext if ext else name
                if candidate not in search_names:
                    search_names.append(candidate)

    for name in search_names:
        found = which(name)
        if found:
            return found

    dirs: List[Path] = []
    if extra_dirs:
        dirs.extend(Path(d) for d in extra_dirs if d)
    dirs.extend(default_search_dirs(system))

    # Also scan managed install root children
    managed = Path.home() / ".esim_toolmanager"
    if managed.is_dir():
        dirs.append(managed)
        for child in managed.iterdir():
            if child.is_dir():
                dirs.append(child)

    seen_dirs = set()
    for directory in dirs:
        try:
            key = str(directory.resolve()) if directory.exists() else str(directory)
        except OSError:
            key = str(directory)
        if key in seen_dirs:
            continue
        seen_dirs.add(key)
        if not directory.is_dir():
            continue
        for name in search_names:
            candidate = directory / name
            if candidate.is_file():
                return str(candidate)
            # Windows: allow name without extension when .cmd/.exe exists
            if normalize_system(system) == "windows":
                for ext in (".exe", ".cmd", ".bat"):
                    alt = directory / f"{Path(name).stem}{ext}"
                    if alt.is_file():
                        return str(alt)
    return None


def detect_package_managers(system: Optional[str] = None) -> List[str]:
    """Return available package managers in preferred order for this OS."""
    system = normalize_system(system)
    found: List[str] = []

    if system == "windows":
        ordered = [("winget", "winget"), ("choco", "chocolatey"), ("scoop", "scoop")]
        for cmd, name in ordered:
            if command_exists(cmd) and name not in found:
                found.append(name)
    elif system == "darwin":
        if command_exists("brew") or any(
            (p / "bin" / "brew").is_file() for p in _homebrew_prefixes()
        ):
            found.append("brew")
    else:
        ordered = [
            ("apt-get", "apt"),
            ("apt", "apt"),
            ("dnf", "dnf"),
            ("yum", "dnf"),
            ("pacman", "pacman"),
            ("zypper", "zypper"),
            ("flatpak", "flatpak"),
        ]
        for cmd, name in ordered:
            if command_exists(cmd) and name not in found:
                found.append(name)
    return found


def get_platform_info() -> PlatformInfo:
    system = normalize_system()
    info = PlatformInfo(
        system=system,
        release=platform.release(),
        machine=platform.machine(),
        available_package_managers=detect_package_managers(system),
        python_executable=python_executable(),
    )
    logger.info(
        "Platform: %s %s (%s); package managers: %s",
        info.system,
        info.release,
        info.machine,
        ", ".join(info.available_package_managers) or "none detected",
    )
    return info


def catalog_pm_key(pm: str) -> str:
    """Map detected package manager name to tools.yaml packages key."""
    mapping = {
        "apt": "apt",
        "apt-get": "apt",
        "dnf": "dnf",
        "yum": "dnf",
        "pacman": "pacman",
        "zypper": "zypper",
        "flatpak": "flatpak",
        "brew": "brew",
        "winget": "winget",
        "chocolatey": "chocolatey",
        "choco": "chocolatey",
        "scoop": "scoop",
        "pip": "pip",
    }
    return mapping.get(pm, pm)


def build_pm_command(pm: str, packages: List[str]) -> Optional[List[str]]:
    """Build a package-manager install command (OS-agnostic helper)."""
    if not packages:
        return None
    if pm == "apt":
        return ["sudo", "apt-get", "install", "-y", *packages]
    if pm == "dnf":
        return ["sudo", "dnf", "install", "-y", *packages]
    if pm == "pacman":
        return ["sudo", "pacman", "-S", "--noconfirm", *packages]
    if pm == "zypper":
        return ["sudo", "zypper", "install", "-y", *packages]
    if pm == "flatpak":
        return ["flatpak", "install", "-y", "flathub", *packages]
    if pm == "brew":
        return ["brew", "install", *packages]
    if pm == "winget":
        cmd = [
            "winget",
            "install",
            "--accept-package-agreements",
            "--accept-source-agreements",
        ]
        for pkg in packages:
            cmd.extend(["--id", pkg, "-e"])
        return cmd
    if pm == "chocolatey":
        return ["choco", "install", "-y", *packages]
    if pm == "scoop":
        return ["scoop", "install", *packages]
    if pm == "pip":
        return [python_executable(), "-m", "pip", "install", *packages]
    return None


def install_plan_matrix(tool: Dict) -> Dict[str, Dict[str, List[str]]]:
    """
    Return install commands for every supported OS in the catalog.

    Used by `plan` so reviewers can see Windows/Linux/macOS support without
    running the tool on each OS.
    """
    matrix: Dict[str, Dict[str, List[str]]] = {}
    packages = tool.get("packages") or {}
    download = tool.get("download") or {}
    for os_name in ("windows", "linux", "darwin"):
        os_packages = packages.get(os_name) or {}
        matrix[os_name] = {}
        if download.get("local_bundle"):
            matrix[os_name]["local_bundle"] = [
                f"<manager local install of {tool.get('display_name', 'tool')}>"
            ]
            continue
        if not os_packages and (tool.get("dependencies") or {}).get("python"):
            from esim_toolmanager.core.dependency import python_requirements_for_host

            specs, _profile = python_requirements_for_host(tool.get("dependencies") or {})
            matrix[os_name]["pip"] = build_pm_command("pip", specs) or []
        for pm, pkgs in os_packages.items():
            cmd = build_pm_command(pm, list(pkgs))
            if cmd:
                matrix[os_name][pm] = cmd
        archive = download.get(f"{os_name}_archive") or {}
        archive_urls: List[str] = []
        for item in [archive.get("url"), *(archive.get("urls") or [])]:
            if item and str(item) not in archive_urls:
                archive_urls.append(str(item))
        if archive_urls:
            matrix[os_name]["portable_archive"] = [
                "download+extract",
                archive_urls[0],
            ]
    return matrix
