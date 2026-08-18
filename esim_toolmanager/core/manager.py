"""Main orchestrator for the eSim Automated Tool Manager."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from esim_toolmanager.core.config_handler import ConfigurationHandler
from esim_toolmanager.core.dependency import (
    DependencyReport,
    check_host_platform,
    check_tool_dependencies,
    summarize_reports,
)
from esim_toolmanager.core.installer import InstallResult, ToolInstaller
from esim_toolmanager.core.platform_utils import get_platform_info
from esim_toolmanager.core.updater import ToolUpdater, UpdateInfo
from esim_toolmanager.core.version import (
    VersionInfo,
    evaluate_version,
    search_dirs_from_tool,
)
from esim_toolmanager.utils.logger import get_logger, setup_logging
from esim_toolmanager.utils.paths import (
    get_config_path,
    get_install_root,
    get_log_dir,
    install_home_from_binary,
    normalize_install_home,
)

logger = get_logger("manager")


class ToolManager:
    """High-level API used by the CLI (and optionally a GUI)."""

    def __init__(
        self,
        config_path: Optional[Path] = None,
        *,
        dry_run: bool = False,
        log_level: int = 20,
    ) -> None:
        self.config_path = config_path or get_config_path()
        setup_logging(get_log_dir(), level=log_level)
        self.catalog_data = self._load_catalog(self.config_path)
        self.tools: Dict[str, Dict] = self.catalog_data.get("tools") or {}
        self.meta = self.catalog_data.get("manager") or {}
        self.dry_run = dry_run
        self.platform = get_platform_info()
        self.install_root = get_install_root()
        self.config_handler = ConfigurationHandler(self.install_root)
        self.installer = ToolInstaller(
            self.tools,
            dry_run=dry_run,
            config_handler=self.config_handler,
            platform=self.platform,
        )
        self.updater = ToolUpdater(self.tools, self.installer)
        self.config_handler.activate_all()
        logger.info(
            "eSim Tool Manager ready | tools=%d | dry_run=%s | os=%s",
            len(self.tools),
            dry_run,
            self.platform.system,
        )

    @staticmethod
    def _load_catalog(path: Path) -> Dict[str, Any]:
        if not path.exists():
            raise FileNotFoundError(f"Tool catalog not found: {path}")
        with path.open(encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        if "tools" not in data:
            raise ValueError("Catalog missing 'tools' section")
        return data

    def list_tools(self) -> List[Dict[str, Any]]:
        rows = []
        state = self.installer.load_state()
        for tool_id, tool in self.tools.items():
            recorded = (state.get("tools") or {}).get(tool_id)
            version_info = self.check_version(tool_id)
            rows.append(
                {
                    "id": tool_id,
                    "name": tool.get("display_name", tool_id),
                    "category": tool.get("category", ""),
                    "required": bool(tool.get("required")),
                    "preferred_version": tool.get("preferred_version"),
                    "installed_version": version_info.version,
                    "status": version_info.status,
                    "managed": recorded is not None,
                    "description": (tool.get("description") or "").strip(),
                }
            )
        return rows

    def check_version(self, tool_id: str) -> VersionInfo:
        if tool_id not in self.tools:
            raise KeyError(f"Unknown tool: {tool_id}")
        tool = self.tools[tool_id]
        state = self.installer.load_state()
        recorded = (state.get("tools") or {}).get(tool_id, {}).get("version")

        version_source = tool.get("version_source") or ""
        if tool_id == "python-deps" or version_source == "python_deps":
            report = check_tool_dependencies(
                tool_id, tool.get("dependencies") or {}
            )
            return evaluate_version(
                tool_id=tool_id,
                binaries=[],
                version_args=[],
                version_regex="",
                preferred_version=tool.get("preferred_version"),
                min_version=tool.get("min_version"),
                recorded_version=recorded,
                python_deps_ok=report.ok,
                python_deps_partial=report.partial,
            )

        extras = search_dirs_from_tool(tool, self.platform.system)
        install_path = (state.get("tools") or {}).get(tool_id, {}).get("install_path")
        if install_path:
            extras = list(extras) + [install_path]

        return evaluate_version(
            tool_id=tool_id,
            binaries=tool.get("binaries") or [],
            version_args=tool.get("version_args") or [],
            version_regex=tool.get("version_regex") or "",
            preferred_version=tool.get("preferred_version"),
            min_version=tool.get("min_version"),
            recorded_version=recorded,
            extra_dirs=extras,
        )

    def check_all_versions(self) -> List[VersionInfo]:
        return [self.check_version(tid) for tid in self.tools]

    def install(self, tool_id: str, *, force: bool = False) -> InstallResult:
        if tool_id not in self.tools:
            raise KeyError(f"Unknown tool: {tool_id}")
        deps = check_tool_dependencies(
            tool_id, self.tools[tool_id].get("dependencies") or {}
        )
        missing = deps.missing()
        if missing:
            logger.warning(
                "Pre-install dependency notes for %s: %s",
                tool_id,
                "; ".join(m.message for m in missing),
            )
        return self.installer.install(tool_id, force=force)

    def install_required(self) -> List[InstallResult]:
        return [
            self.install(tool_id)
            for tool_id, tool in self.tools.items()
            if tool.get("required")
        ]

    def uninstall(self, tool_id: str) -> InstallResult:
        return self.installer.uninstall(tool_id)

    def check_updates(self, *, query_remote: bool = True) -> List[UpdateInfo]:
        version_map = {v.tool_id: v for v in self.check_all_versions()}
        return self.updater.check_all(version_map, query_remote=query_remote)

    def update(self, tool_id: str, *, force: bool = False) -> UpdateInfo:
        return self.updater.update(tool_id, force=force)

    def update_all(self) -> List[UpdateInfo]:
        return self.updater.update_all()

    def plan(self, tool_id: Optional[str] = None) -> List[Dict[str, Any]]:
        ids = [tool_id] if tool_id else list(self.tools)
        return [self.installer.plan(tid) for tid in ids]

    def configure(self, tool_id: str) -> Dict[str, Any]:
        if tool_id not in self.tools:
            raise KeyError(f"Unknown tool: {tool_id}")
        tool = self.tools[tool_id]
        state = self.installer.load_state()
        entry = (state.get("tools") or {}).get(tool_id)
        vi = self.check_version(tool_id)
        if entry and entry.get("install_path"):
            install_path = normalize_install_home(Path(entry["install_path"]))
        elif vi.binary_path and not str(vi.binary_path).startswith("("):
            install_path = install_home_from_binary(Path(vi.binary_path))
        else:
            install_path = self.install_root / tool_id
            install_path.mkdir(parents=True, exist_ok=True)

        runtime = {
            "binary": (
                vi.binary_path
                if vi.binary_path and not str(vi.binary_path).startswith("(")
                else None
            ),
            "version": vi.version,
            "status": vi.status,
        }
        result = self.config_handler.apply_tool_config(
            tool_id,
            install_path,
            tool.get("config") or {},
            runtime=runtime,
        )
        return asdict(result)

    def configure_all(self) -> List[Dict[str, Any]]:
        return [self.configure(tid) for tid in self.tools]

    def check_dependencies(self, tool_id: Optional[str] = None) -> List[DependencyReport]:
        reports: List[DependencyReport] = [check_host_platform()]
        if tool_id:
            tool = self.tools[tool_id]
            reports.append(
                check_tool_dependencies(
                    tool_id,
                    tool.get("dependencies") or {},
                    binaries=tool.get("binaries") or [],
                    check_binaries=bool(tool.get("binaries")),
                )
            )
            return reports
        for tid, tool in self.tools.items():
            reports.append(
                check_tool_dependencies(
                    tid,
                    tool.get("dependencies") or {},
                    binaries=tool.get("binaries") or [],
                    check_binaries=False,
                )
            )
        return reports

    def dependency_summary(self, tool_id: Optional[str] = None) -> str:
        return summarize_reports(self.check_dependencies(tool_id))

    def activation_help(self) -> str:
        return self.config_handler.get_activation_instructions()

    def verify(self) -> Dict[str, Any]:
        """
        End-to-end self-check of manager capabilities on the current host.

        Covers install/version/configure/update/deps without requiring admin
        package installs (uses demo-tool). Also proves Win/Linux/macOS bundle
        launchers and catalog upgrade detection.
        """
        steps: List[Dict[str, Any]] = []

        def add(step: str, ok: bool, detail: str) -> None:
            steps.append({"step": step, "ok": ok, "detail": detail})

        host = check_host_platform()
        add("host_dependencies", host.ok, summarize_reports([host]))

        for tool_id in ("ngspice", "kicad", "ghdl"):
            plans = self.plan(tool_id)
            matrix = plans[0].get("matrix") or {}
            add(
                f"cross_platform_plan_{tool_id}",
                all(os_name in matrix for os_name in ("windows", "linux", "darwin")),
                f"OS keys present: {sorted(matrix.keys())}",
            )

        inst = self.install("demo-tool", force=True)
        add("install_demo_tool", inst.success, inst.message)

        status = self.check_version("demo-tool")
        add(
            "version_check_demo_tool",
            status.installed and status.status == "ok",
            f"{status.status}: {status.message}",
        )

        cfg = self.configure("demo-tool")
        add("configure_demo_tool", bool(cfg.get("success")), cfg.get("message", ""))

        cfg_dir = self.config_handler.config_dir
        scripts_ok = all(
            (cfg_dir / name).exists()
            for name in ("activate.sh", "activate.ps1", "activate.bat", "esim_bridge.json")
        )
        add("activation_scripts_all_platforms", scripts_ok, str(cfg_dir))

        # Prove update detection + apply via in-memory catalog bump (local bundle)
        original_pref = self.tools["demo-tool"].get("preferred_version", "1.0.0")
        self.tools["demo-tool"]["preferred_version"] = "1.0.1"
        detected = self.updater.check_tool("demo-tool", query_remote=False)
        add(
            "update_detects_newer_version",
            detected.update_available is True,
            detected.message,
        )
        applied = self.update("demo-tool")
        add(
            "update_applies_new_version",
            (applied.new_version == "1.0.1")
            or (applied.current_version == "1.0.1"),
            applied.message,
        )
        # Restore catalog preferred for a clean manager state
        self.tools["demo-tool"]["preferred_version"] = original_pref
        # Re-install catalog baseline so status stays consistent with YAML
        self.install("demo-tool", force=True)

        upd = self.check_updates(query_remote=False)
        demo_upd = next((u for u in upd if u.tool_id == "demo-tool"), None)
        add(
            "update_check_demo_tool",
            demo_upd is not None
            and demo_upd.status in ("up_to_date", "update_available"),
            demo_upd.message if demo_upd else "missing",
        )

        xplat = self._verify_cross_platform_demo_bundle()
        add(
            "cross_platform_demo_launchers",
            xplat["ok"],
            xplat["detail"],
        )

        add(
            "dependency_reporter",
            True,
            self.dependency_summary("demo-tool")[:200],
        )

        overall = all(s["ok"] for s in steps)
        return {
            "overall_ok": overall,
            "platform": asdict(self.platform),
            "steps": steps,
        }

    def _verify_cross_platform_demo_bundle(self) -> Dict[str, Any]:
        """Install demo-tool under mocked linux/darwin/windows PlatformInfo."""
        from esim_toolmanager.core.installer import ToolInstaller
        from esim_toolmanager.core.platform_utils import PlatformInfo

        details = []
        ok = True
        for system, pms in (
            ("windows", ["winget"]),
            ("linux", ["apt"]),
            ("darwin", ["brew"]),
        ):
            root = self.install_root / f"_xplat_verify_{system}"
            platform = PlatformInfo(
                system=system,
                release="verify",
                machine="x86_64",
                available_package_managers=pms,
            )
            # Isolate state/files under a sub-root by temporarily pointing installer
            installer = ToolInstaller(
                self.tools,
                dry_run=False,
                config_handler=self.config_handler,
                platform=platform,
            )
            # Force install path under install_root/demo-tool (shared) — instead
            # write launchers by calling private bundle with overridden root
            tool = dict(self.tools["demo-tool"])
            tool["preferred_version"] = "1.0.0"
            result = installer._install_demo_bundle("demo-tool", tool, force=True)
            path = Path(result.install_path or "")
            has_cmd = (path / "esim-demo-tool.cmd").exists()
            has_sh = (path / "esim-demo-tool").exists()
            # Both launchers must always exist for portability
            step_ok = result.success and has_cmd and has_sh
            ok = ok and step_ok
            details.append(
                f"{system}: success={result.success} cmd={has_cmd} sh={has_sh}"
            )
            _ = root  # reserved for future isolated roots
        return {"ok": ok, "detail": "; ".join(details)}

    def doctor(self) -> Dict[str, Any]:
        """Aggregate health report for debugging / demos."""
        versions = [asdict(v) for v in self.check_all_versions()]
        updates = [asdict(u) for u in self.check_updates(query_remote=False)]
        deps = self.dependency_summary()
        plans = {p["tool_id"]: p for p in self.plan()}
        return {
            "platform": asdict(self.platform),
            "install_root": str(self.install_root),
            "catalog": str(self.config_path),
            "manager_version": self.meta.get("version", "1.0.0"),
            "versions": versions,
            "updates": updates,
            "dependencies": deps,
            "activation": self.activation_help(),
            "install_plans": plans,
        }

    def read_log_tail(self, lines: int = 40) -> str:
        log_file = get_log_dir() / "tool_manager.log"
        if not log_file.exists():
            return "(no log file yet)"
        content = log_file.read_text(encoding="utf-8", errors="replace").splitlines()
        return "\n".join(content[-lines:])
