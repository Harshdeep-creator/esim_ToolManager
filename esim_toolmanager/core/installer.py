"""Tool installation via package managers or local bundles (cross-platform)."""

from __future__ import annotations

import json
import os
import stat
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from esim_toolmanager.core.config_handler import ConfigurationHandler
from esim_toolmanager.core.dependency import python_requirements_for_host
from esim_toolmanager.core.platform_utils import (
    PlatformInfo,
    build_pm_command,
    catalog_pm_key,
    find_executable,
    get_platform_info,
    install_plan_matrix,
    python_executable,
    run_command,
)
from esim_toolmanager.core.version import (
    compare_versions,
    detect_binary_version,
    is_compatible,
    search_dirs_from_tool,
)
from esim_toolmanager.utils.logger import get_logger
from esim_toolmanager.utils.paths import (
    get_install_root,
    get_state_path,
    install_home_from_binary,
)

logger = get_logger("installer")


@dataclass
class InstallResult:
    tool_id: str
    success: bool
    method: str
    version: Optional[str] = None
    install_path: Optional[str] = None
    message: str = ""
    command: Optional[List[str]] = None
    already_present: bool = False


class ToolInstaller:
    """Install tools using the best available method for the host OS."""

    def __init__(
        self,
        tools_catalog: Dict,
        *,
        dry_run: bool = False,
        config_handler: Optional[ConfigurationHandler] = None,
        platform: Optional[PlatformInfo] = None,
    ) -> None:
        self.catalog = tools_catalog
        self.dry_run = dry_run
        self.install_root = get_install_root()
        self.install_root.mkdir(parents=True, exist_ok=True)
        self.state_path = get_state_path()
        self.config_handler = config_handler or ConfigurationHandler(self.install_root)
        self.platform = platform or get_platform_info()

    def load_state(self) -> Dict:
        if not self.state_path.exists():
            return {"tools": {}}
        try:
            return json.loads(self.state_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            logger.warning("Corrupt state file; starting fresh")
            return {"tools": {}}

    def save_state(self, state: Dict) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")

    def record_install(
        self,
        tool_id: str,
        *,
        version: str,
        method: str,
        install_path: str,
    ) -> None:
        state = self.load_state()
        state.setdefault("tools", {})[tool_id] = {
            "version": version,
            "method": method,
            "install_path": install_path,
            "configured": True,
            "platform": self.platform.system,
        }
        self.save_state(state)

    def plan(self, tool_id: str) -> Dict:
        """Return install command matrix for Windows, Linux, and macOS."""
        if tool_id not in self.catalog:
            return {"tool_id": tool_id, "error": "unknown tool"}
        tool = self.catalog[tool_id]
        return {
            "tool_id": tool_id,
            "display_name": tool.get("display_name", tool_id),
            "preferred_version": tool.get("preferred_version"),
            "current_platform": self.platform.system,
            "available_package_managers": list(self.platform.available_package_managers),
            "matrix": install_plan_matrix(tool),
        }

    def install(self, tool_id: str, *, force: bool = False) -> InstallResult:
        if tool_id not in self.catalog:
            return InstallResult(
                tool_id=tool_id,
                success=False,
                method="none",
                message=f"Unknown tool: {tool_id}",
            )

        tool = self.catalog[tool_id]
        logger.info("Installing %s (%s)", tool.get("display_name", tool_id), tool_id)

        if tool_id == "python-deps":
            return self._install_python_deps(tool)

        if (tool.get("download") or {}).get("local_bundle"):
            return self._install_demo_bundle(tool_id, tool, force=force)

        # If a compatible binary already exists, adopt it (no privileged reinstall)
        if not force:
            adopted = self._try_adopt_existing(tool_id, tool)
            if adopted is not None:
                return adopted

        pm_result = self._install_via_package_manager(tool_id, tool)
        if pm_result is not None:
            if (
                pm_result.success
                and pm_result.install_path
                and not self.dry_run
                and not str(pm_result.method).startswith("dry-run")
            ):
                # Probe real version after install (all OSes)
                version = self._probe_version(tool_id, tool) or pm_result.version
                pm_result.version = version
                self.config_handler.apply_tool_config(
                    tool_id,
                    Path(pm_result.install_path),
                    tool.get("config") or {},
                )
                self.record_install(
                    tool_id,
                    version=version or tool.get("preferred_version", "unknown"),
                    method=pm_result.method,
                    install_path=pm_result.install_path,
                )
            return pm_result

        # Portable archive fallback (e.g. official Ngspice Windows .7z)
        archive_result = self._install_from_archive(tool_id, tool, force=force)
        if archive_result is not None:
            return archive_result

        download = tool.get("download") or {}
        hint = (
            download.get(f"{self.platform.system}_url")
            or download.get(f"{self.platform.system}_note")
            or download.get("windows_url")
            or download.get("linux_url")
            or download.get("darwin_url")
            or "See tool documentation for your OS"
        )
        # Include full matrix so lack of a PM is not a silent Windows-only dead end
        matrix = install_plan_matrix(tool)
        msg = (
            f"No usable package manager for {tool_id} on {self.platform.system}. "
            f"Manual/alternate options: {hint}. "
            f"Planned commands by OS are available via: esim-tm plan {tool_id}"
        )
        logger.error(msg)
        return InstallResult(
            tool_id=tool_id,
            success=False,
            method="manual",
            message=msg + f" | matrix_keys={list(matrix.keys())}",
        )

    def _install_from_archive(
        self, tool_id: str, tool: Dict, *, force: bool = False
    ) -> Optional[InstallResult]:
        """Download and extract a portable archive when configured for this OS."""
        from esim_toolmanager.core.archive_install import (
            archive_urls_from_spec,
            cleanup_dir,
            download_first_url,
            extract_archive,
            find_under,
        )

        download = tool.get("download") or {}
        key = f"{self.platform.system}_archive"
        spec = download.get(key)
        if not spec:
            return None

        urls = archive_urls_from_spec(spec)
        if not urls:
            return None
        url = urls[0]

        version = str(spec.get("version") or tool.get("preferred_version") or "unknown")
        install_path = self.install_root / tool_id
        binary_rel = spec.get("binary_relative") or ""

        if self.dry_run:
            return InstallResult(
                tool_id=tool_id,
                success=True,
                method=f"dry-run:archive:{self.platform.system}",
                version=version,
                install_path=str(install_path),
                message=f"Dry-run: would download portable archive from {url}",
                command=["download", url],
            )

        # Reuse existing extract if binary already present and not forcing
        if not force:
            existing = find_under(install_path, binary_rel) if binary_rel else None
            if existing and existing.exists():
                bin_dir = existing.parent
                os.environ["PATH"] = str(bin_dir) + os.pathsep + os.environ.get("PATH", "")
                probed = self._probe_version(tool_id, tool) or version
                self.config_handler.apply_tool_config(
                    tool_id, install_path, tool.get("config") or {}
                )
                # Also append archive-specific path entries
                for entry in spec.get("path_append") or []:
                    rendered = entry.format(install_path=str(install_path).replace("\\", "/"))
                    os.environ["PATH"] = (
                        str(Path(rendered)) + os.pathsep + os.environ.get("PATH", "")
                    )
                self.record_install(
                    tool_id,
                    version=probed,
                    method="archive",
                    install_path=str(install_path),
                )
                return InstallResult(
                    tool_id=tool_id,
                    success=True,
                    method="archive",
                    version=probed,
                    install_path=str(install_path),
                    message=f"Reused portable {tool_id} {probed} at {existing}",
                    already_present=True,
                )

        try:
            cleanup_dir(install_path)
            install_path.mkdir(parents=True, exist_ok=True)
            parts = url.rstrip("/").split("/")
            if parts and parts[-1] == "download" and len(parts) >= 2:
                archive_name = parts[-2]
            else:
                archive_name = parts[-1] if parts else f"{tool_id}-{version}.7z"
            if not archive_name or "." not in archive_name:
                archive_name = f"{tool_id}-{version}.7z"
            archive_path = self.install_root / "cache" / archive_name
            download_first_url(urls, archive_path)
            extract_archive(archive_path, install_path)
        except Exception as exc:  # noqa: BLE001
            logger.error("Archive install failed for %s: %s", tool_id, exc)
            return InstallResult(
                tool_id=tool_id,
                success=False,
                method="archive",
                message=f"Archive install failed: {exc}",
            )

        binary = find_under(install_path, binary_rel) if binary_rel else None
        if not binary:
            # fallback: search common names
            for name in tool.get("binaries") or []:
                binary = find_under(install_path, name)
                if binary:
                    break
        if not binary:
            return InstallResult(
                tool_id=tool_id,
                success=False,
                method="archive",
                install_path=str(install_path),
                message=f"Archive extracted but binary not found ({binary_rel})",
            )

        bin_dir = binary.parent
        os.environ["PATH"] = str(bin_dir) + os.pathsep + os.environ.get("PATH", "")
        for entry in spec.get("path_append") or []:
            rendered = entry.format(install_path=str(install_path).replace("\\", "/"))
            os.environ["PATH"] = str(Path(rendered)) + os.pathsep + os.environ.get(
                "PATH", ""
            )

        cfg = dict(tool.get("config") or {})
        path_append = list(cfg.get("path_append") or [])
        path_append.extend(spec.get("path_append") or [])
        cfg["path_append"] = path_append
        self.config_handler.apply_tool_config(tool_id, install_path, cfg)

        probed = self._probe_version(tool_id, tool) or version
        self.record_install(
            tool_id,
            version=probed,
            method="archive",
            install_path=str(install_path),
        )
        logger.info("Installed portable %s %s via archive", tool_id, probed)
        return InstallResult(
            tool_id=tool_id,
            success=True,
            method="archive",
            version=probed,
            install_path=str(install_path),
            message=f"Installed portable {tool_id} {probed} from official archive -> {binary}",
        )

    def _probe_version(self, tool_id: str, tool: Dict) -> Optional[str]:
        version, _path, _raw = self._probe_binary(tool_id, tool)
        return version

    def _probe_binary(
        self, tool_id: str, tool: Dict
    ) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        extras = search_dirs_from_tool(tool, self.platform.system)
        state = self.load_state()
        recorded_path = (state.get("tools") or {}).get(tool_id, {}).get("install_path")
        if recorded_path:
            extras = list(extras) + [recorded_path]
        return detect_binary_version(
            tool.get("binaries") or [],
            tool.get("version_args") or [],
            tool.get("version_regex") or "",
            extra_dirs=extras,
        )

    def _try_adopt_existing(self, tool_id: str, tool: Dict) -> Optional[InstallResult]:
        """Register an already-installed compatible tool without reinstalling."""
        version, path, _raw = self._probe_binary(tool_id, tool)
        if not version or not path:
            return None
        min_version = tool.get("min_version")
        if min_version and not is_compatible(version, min_version):
            logger.info(
                "Found %s %s but below minimum %s - will try package install",
                tool_id,
                version,
                min_version,
            )
            return None

        preferred = tool.get("preferred_version") or version
        install_path = str(install_home_from_binary(Path(path)))
        note = (
            "meets preferred"
            if compare_versions(version, preferred) >= 0
            else f"below preferred {preferred} (run update when a newer package is available)"
        )

        if self.dry_run:
            return InstallResult(
                tool_id=tool_id,
                success=True,
                method="dry-run:adopt-existing",
                version=version,
                install_path=install_path,
                message=f"Dry-run: would adopt existing {tool_id} {version} at {path} ({note})",
                already_present=True,
            )

        self.config_handler.apply_tool_config(
            tool_id, Path(install_path), tool.get("config") or {},
            runtime={"binary": path, "version": version},
        )
        self.record_install(
            tool_id,
            version=version,
            method="adopt-existing",
            install_path=install_path,
        )
        logger.info("Adopted existing %s %s from %s", tool_id, version, path)
        return InstallResult(
            tool_id=tool_id,
            success=True,
            method="adopt-existing",
            version=version,
            install_path=install_path,
            message=f"Adopted existing {tool_id} {version} from {path} ({note})",
            already_present=True,
        )

    def _install_via_package_manager(
        self, tool_id: str, tool: Dict
    ) -> Optional[InstallResult]:
        packages = (tool.get("packages") or {}).get(self.platform.system) or {}
        if not packages:
            return None

        attempted = 0
        for pm in self.platform.available_package_managers:
            key = catalog_pm_key(pm)
            pkg_list = packages.get(key)
            if not pkg_list:
                continue
            cmd = build_pm_command(key, list(pkg_list))
            if not cmd:
                continue
            attempted += 1

            if self.dry_run:
                logger.info("[dry-run] Would run: %s", " ".join(cmd))
                return InstallResult(
                    tool_id=tool_id,
                    success=True,
                    method=f"dry-run:{key}",
                    version=tool.get("preferred_version"),
                    install_path=str(self.install_root / tool_id),
                    message=f"Dry-run: {' '.join(cmd)}",
                    command=cmd,
                )

            logger.info("Installing via %s: %s", key, " ".join(cmd))
            try:
                result = run_command(cmd, timeout=900, check=False)
            except Exception as exc:  # noqa: BLE001
                logger.error("Package manager failed: %s", exc)
                continue

            if result.returncode != 0:
                logger.warning(
                    "%s install failed (code %s): %s",
                    key,
                    result.returncode,
                    (result.stderr or result.stdout or "")[:500],
                )
                continue

            install_path = self.install_root / tool_id
            install_path.mkdir(parents=True, exist_ok=True)
            version = self._probe_version(tool_id, tool) or tool.get(
                "preferred_version", "unknown"
            )
            extras = search_dirs_from_tool(tool, self.platform.system)
            binary_path = None
            for binary in tool.get("binaries") or []:
                binary_path = find_executable(
                    [binary], extra_dirs=list(extras) + [str(install_path)]
                )
                if binary_path:
                    break

            home = (
                install_home_from_binary(Path(binary_path))
                if binary_path
                else install_path
            )
            msg = f"Installed {tool_id} via {key} (version {version})"
            if not binary_path:
                msg += (
                    " — package manager reported success, but the binary is not "
                    "on PATH yet. Open a new shell or run: esim-tm configure "
                    f"{tool_id}"
                )
            return InstallResult(
                tool_id=tool_id,
                success=True,
                method=key,
                version=version,
                install_path=str(home),
                message=msg,
                command=cmd,
            )

        # Dry-run preview: if no installed PM matches, still show the first
        # catalog command for this OS (honest preview, not an executed install).
        if self.dry_run and attempted == 0:
            for pm_name, pkg_list in packages.items():
                cmd = build_pm_command(pm_name, list(pkg_list))
                if not cmd:
                    continue
                return InstallResult(
                    tool_id=tool_id,
                    success=True,
                    method=f"dry-run:plan:{pm_name}",
                    version=tool.get("preferred_version"),
                    install_path=str(self.install_root / tool_id),
                    message=(
                        f"Dry-run preview (host lacks '{pm_name}'): {' '.join(cmd)}. "
                        f"Install that package manager, or see: esim-tm plan {tool_id}"
                    ),
                    command=cmd,
                )
        return None

    def _install_python_deps(self, tool: Dict) -> InstallResult:
        import sys

        specs, profile = python_requirements_for_host(tool.get("dependencies") or {})
        if not specs:
            return InstallResult(
                tool_id="python-deps",
                success=True,
                method="pip",
                version=tool.get("preferred_version"),
                message="No Python dependencies listed",
            )

        py_note = ""
        if profile != "esim-2.5":
            py_note = (
                f" Host Python is {sys.version_info.major}.{sys.version_info.minor};"
                f" installing {profile} compatible specs (eSim 2.5 official pins"
                " need Python 3.10 or 3.11)."
            )

        cmd = [python_executable(), "-m", "pip", "install", *specs]
        if self.dry_run:
            logger.info("[dry-run] Would run: %s", " ".join(cmd))
            return InstallResult(
                tool_id="python-deps",
                success=True,
                method="dry-run:pip",
                version=tool.get("preferred_version"),
                install_path=str(self.install_root / "python-deps"),
                message=f"Dry-run: {' '.join(cmd)}",
                command=cmd,
            )

        logger.info("Installing Python dependencies via pip")
        result = run_command(cmd, timeout=900, check=False)
        ok = result.returncode == 0
        path = self.install_root / "python-deps"
        path.mkdir(parents=True, exist_ok=True)
        if ok:
            self.record_install(
                "python-deps",
                version=tool.get("preferred_version", "esim-2.5"),
                method="pip",
                install_path=str(path),
            )
        return InstallResult(
            tool_id="python-deps",
            success=ok,
            method="pip",
            version=tool.get("preferred_version"),
            install_path=str(path),
            message=(
                ("Python dependencies installed" + py_note)
                if ok
                else (
                    f"pip failed: {(result.stderr or result.stdout or '')[:400]}"
                    + py_note
                )
            ),
            command=cmd,
        )

    def _install_demo_bundle(
        self, tool_id: str, tool: Dict, *, force: bool = False
    ) -> InstallResult:
        """Create a portable demo tool with Windows + Unix launchers."""
        version = tool.get("preferred_version", "1.0.0")
        install_path = self.install_root / tool_id
        script_name = "esim-demo-tool.py"
        script_path = install_path / script_name
        py = python_executable()

        if self.dry_run:
            msg = f"Dry-run: would create demo tool {version} at {install_path}"
            logger.info(msg)
            return InstallResult(
                tool_id=tool_id,
                success=True,
                method="dry-run:local_bundle",
                version=version,
                install_path=str(install_path),
                message=msg,
            )

        # Idempotent unless force or version mismatch
        state = self.load_state()
        existing = (state.get("tools") or {}).get(tool_id)
        if (
            not force
            and existing
            and existing.get("version") == version
            and script_path.exists()
        ):
            self.config_handler.apply_tool_config(
                tool_id, install_path, tool.get("config") or {}
            )
            os.environ["PATH"] = str(install_path) + os.pathsep + os.environ.get("PATH", "")
            return InstallResult(
                tool_id=tool_id,
                success=True,
                method="local_bundle",
                version=version,
                install_path=str(install_path),
                message=f"Demo tool {version} already installed at {install_path}",
            )

        install_path.mkdir(parents=True, exist_ok=True)
        script_body = textwrap.dedent(
            f'''\
            #!/usr/bin/env python3
            """eSim Tool Manager demo tool - proof-of-concept binary."""
            import argparse
            import sys

            VERSION = "{version}"

            def main():
                parser = argparse.ArgumentParser(prog="esim-demo-tool")
                parser.add_argument("--version", action="store_true")
                parser.add_argument("cmd", nargs="?", default="info")
                args = parser.parse_args()
                if args.version or args.cmd == "version":
                    print(f"esim-demo-tool {{VERSION}}")
                    return 0
                print("eSim Demo Tool - managed by eSim Automated Tool Manager")
                print(f"Version: {{VERSION}}")
                print(f"Python: {{sys.executable}}")
                return 0

            if __name__ == "__main__":
                sys.exit(main())
            '''
        )
        script_path.write_text(script_body, encoding="utf-8")

        # Always write BOTH launcher styles so the bundle is portable across OSes
        cmd_wrapper = install_path / "esim-demo-tool.cmd"
        cmd_wrapper.write_text(
            f'@echo off\r\n"{py}" "%~dp0{script_name}" %*\r\n',
            encoding="utf-8",
        )
        sh_wrapper = install_path / "esim-demo-tool"
        sh_wrapper.write_text(
            "#!/usr/bin/env bash\n"
            f'exec "{py}" "$(dirname "$0")/{script_name}" "$@"\n',
            encoding="utf-8",
        )
        try:
            sh_wrapper.chmod(
                sh_wrapper.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH
            )
        except OSError:
            # Windows may not honor Unix exec bits; .cmd covers Windows.
            pass

        # Cross-launch helper using current interpreter
        py_launcher = install_path / "esim-demo-tool.pyw"
        py_launcher.write_text(
            f'import runpy\nrunpy.run_path(r"{script_path}", run_name="__main__")\n',
            encoding="utf-8",
        )

        meta = {
            "tool_id": tool_id,
            "version": version,
            "script": str(script_path),
            "python": py,
            "platform_installed_on": self.platform.system,
            "launchers": ["esim-demo-tool", "esim-demo-tool.cmd"],
        }
        (install_path / "manifest.json").write_text(
            json.dumps(meta, indent=2), encoding="utf-8"
        )

        self.config_handler.apply_tool_config(
            tool_id, install_path, tool.get("config") or {},
            runtime={
                "binary": str(cmd_wrapper if self.platform.system == "windows" else sh_wrapper),
                "version": version,
            },
        )
        os.environ["PATH"] = str(install_path) + os.pathsep + os.environ.get("PATH", "")

        self.record_install(
            tool_id,
            version=version,
            method="local_bundle",
            install_path=str(install_path),
        )
        logger.info("Demo tool installed at %s", install_path)
        return InstallResult(
            tool_id=tool_id,
            success=True,
            method="local_bundle",
            version=version,
            install_path=str(install_path),
            message=f"Demo tool {version} installed at {install_path}",
        )

    def uninstall(self, tool_id: str) -> InstallResult:
        state = self.load_state()
        entry = state.get("tools", {}).get(tool_id)
        if not entry:
            return InstallResult(
                tool_id=tool_id,
                success=False,
                method="none",
                message=f"{tool_id} is not recorded as installed by this manager",
            )

        method = entry.get("method", "")
        install_path = entry.get("install_path")

        if self.dry_run:
            return InstallResult(
                tool_id=tool_id,
                success=True,
                method=f"dry-run:uninstall:{method}",
                message=f"Dry-run: would uninstall {tool_id}",
            )

        if install_path and method in (
            "local_bundle",
            "pip",
            "archive",
            "dry-run:local_bundle",
        ):
            import shutil

            path = Path(install_path).resolve()
            root = self.install_root.resolve()
            managed = path == (root / tool_id).resolve() or root in path.parents
            if path.exists() and managed and path.is_dir() and tool_id != "python-deps":
                shutil.rmtree(path, ignore_errors=True)
                logger.info("Removed managed files at %s", path)

        self.config_handler.remove_tool_config(tool_id)
        state["tools"].pop(tool_id, None)
        self.save_state(state)
        return InstallResult(
            tool_id=tool_id,
            success=True,
            method=f"uninstall:{method}",
            message=f"Uninstalled managed state for {tool_id}",
        )
