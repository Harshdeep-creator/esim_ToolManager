"""Update / upgrade checks and application for managed tools."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from esim_toolmanager.core.installer import ToolInstaller
from esim_toolmanager.core.pm_query import RemoteVersionInfo, query_remote_for_tool
from esim_toolmanager.core.version import VersionInfo, compare_versions, evaluate_version
from esim_toolmanager.utils.logger import get_logger

logger = get_logger("updater")


@dataclass
class UpdateInfo:
    tool_id: str
    current_version: Optional[str]
    available_version: Optional[str]
    update_available: bool
    status: str
    message: str
    previous_version: Optional[str] = None
    new_version: Optional[str] = None
    remote_source: Optional[str] = None
    remote_queries: List[dict] = field(default_factory=list)


class ToolUpdater:
    """Check for and apply updates to catalog tools."""

    def __init__(self, tools_catalog: Dict, installer: ToolInstaller) -> None:
        self.catalog = tools_catalog
        self.installer = installer

    def _resolve_available_version(
        self, tool_id: str, tool: Dict, *, query_remote: bool = True
    ) -> tuple:
        """Return (available_version, remote_source, remote_query_dicts)."""
        preferred = tool.get("preferred_version")
        available = preferred
        source = "catalog"
        remote_dicts: List[dict] = []

        if not query_remote:
            return available, source, remote_dicts

        # Local bundles / python meta-tools: catalog is source of truth
        if (tool.get("download") or {}).get("local_bundle") or tool_id == "python-deps":
            return available, source, remote_dicts

        try:
            remotes: List[RemoteVersionInfo] = query_remote_for_tool(
                tool_id, tool, self.installer.platform
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("Remote query skipped for %s: %s", tool_id, exc)
            remotes = []

        for info in remotes:
            remote_dicts.append(info.__dict__)
            if not info.remote_version:
                continue
            # Prefer the newest among catalog preferred and remote
            if available is None or compare_versions(info.remote_version, available) > 0:
                available = info.remote_version
                source = f"{info.package_manager}:{info.package_id}"

        return available, source, remote_dicts

    def check_tool(
        self,
        tool_id: str,
        version_info: Optional[VersionInfo] = None,
        *,
        query_remote: bool = True,
    ) -> UpdateInfo:
        tool = self.catalog.get(tool_id)
        if not tool:
            return UpdateInfo(
                tool_id=tool_id,
                current_version=None,
                available_version=None,
                update_available=False,
                status="unknown",
                message=f"Unknown tool: {tool_id}",
            )

        if version_info is None:
            state = self.installer.load_state()
            recorded = (state.get("tools") or {}).get(tool_id, {}).get("version")
            version_source = tool.get("version_source") or ""
            if tool_id == "python-deps" or version_source == "python_deps":
                from esim_toolmanager.core.dependency import check_tool_dependencies

                report = check_tool_dependencies(
                    tool_id, tool.get("dependencies") or {}
                )
                version_info = evaluate_version(
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
            else:
                version_info = evaluate_version(
                    tool_id=tool_id,
                    binaries=tool.get("binaries") or [],
                    version_args=tool.get("version_args") or [],
                    version_regex=tool.get("version_regex") or "",
                    preferred_version=tool.get("preferred_version"),
                    min_version=tool.get("min_version"),
                    recorded_version=recorded,
                )

        available, source, remote_dicts = self._resolve_available_version(
            tool_id, tool, query_remote=query_remote
        )
        current = version_info.version

        if not version_info.installed or version_info.status == "not_installed":
            return UpdateInfo(
                tool_id=tool_id,
                current_version=current,
                available_version=available,
                update_available=False,
                status="not_installed",
                message="Not installed - run install to get the preferred version",
                remote_source=source,
                remote_queries=remote_dicts,
            )

        if version_info.status == "partial":
            return UpdateInfo(
                tool_id=tool_id,
                current_version=current,
                available_version=available,
                update_available=True,
                status="update_available",
                message="Partial install - re-run install/update to satisfy requirements",
                remote_source=source,
                remote_queries=remote_dicts,
            )

        if available and current and compare_versions(current, available) < 0:
            return UpdateInfo(
                tool_id=tool_id,
                current_version=current,
                available_version=available,
                update_available=True,
                status="update_available",
                message=f"Update available: {current} -> {available} (via {source})",
                remote_source=source,
                remote_queries=remote_dicts,
            )

        if version_info.status == "incompatible":
            return UpdateInfo(
                tool_id=tool_id,
                current_version=current,
                available_version=available,
                update_available=True,
                status="update_available",
                message=version_info.message,
                remote_source=source,
                remote_queries=remote_dicts,
            )

        return UpdateInfo(
            tool_id=tool_id,
            current_version=current,
            available_version=available,
            update_available=False,
            status="up_to_date",
            message=f"Up to date ({current}); latest known {available} via {source}",
            remote_source=source,
            remote_queries=remote_dicts,
        )

    def check_all(
        self,
        version_map: Optional[Dict[str, VersionInfo]] = None,
        *,
        query_remote: bool = True,
    ) -> List[UpdateInfo]:
        results = []
        for tid in self.catalog:
            vi = version_map.get(tid) if version_map else None
            results.append(self.check_tool(tid, vi, query_remote=query_remote))
        return results

    def update(self, tool_id: str, *, force: bool = False) -> UpdateInfo:
        """Upgrade a tool to the best known available version."""
        before = self.check_tool(tool_id)
        if before.status == "up_to_date" and not force:
            logger.info("%s is already up to date", tool_id)
            return before

        if before.status == "not_installed":
            logger.info("%s not installed - installing available version", tool_id)

        # For catalog-driven local bundles, temporarily align preferred_version
        tool = self.catalog.get(tool_id) or {}
        original_preferred = tool.get("preferred_version")
        if (
            before.available_version
            and (tool.get("download") or {}).get("local_bundle")
            and before.available_version != original_preferred
        ):
            tool["preferred_version"] = before.available_version

        logger.info(
            "Updating %s: %s -> %s (%s)",
            tool_id,
            before.current_version,
            before.available_version,
            before.remote_source,
        )
        result = self.installer.install(tool_id, force=True)

        if original_preferred is not None and (tool.get("download") or {}).get("local_bundle"):
            # Keep bumped preferred if update targeted a newer catalog override
            pass

        if not result.success:
            return UpdateInfo(
                tool_id=tool_id,
                current_version=before.current_version,
                available_version=before.available_version,
                update_available=True,
                status="failed",
                message=result.message,
                previous_version=before.current_version,
                remote_source=before.remote_source,
                remote_queries=before.remote_queries,
            )

        after = self.check_tool(tool_id, query_remote=False)
        after.previous_version = before.current_version
        after.new_version = result.version or after.current_version
        after.remote_source = before.remote_source
        after.remote_queries = before.remote_queries
        if after.status in ("up_to_date", "ok") or (
            after.current_version
            and before.available_version
            and compare_versions(after.current_version, before.available_version) >= 0
        ):
            after.status = "up_to_date"
            after.update_available = False
            after.message = (
                f"Updated {after.previous_version or 'none'} -> {after.new_version}"
            )
        return after

    def update_all(self, *, only_outdated: bool = True) -> List[UpdateInfo]:
        results: List[UpdateInfo] = []
        for tool_id in self.catalog:
            info = self.check_tool(tool_id)
            if info.status == "update_available":
                results.append(self.update(tool_id))
                continue
            if info.status == "not_installed":
                tool = self.catalog[tool_id]
                if tool.get("required") and not only_outdated:
                    results.append(self.update(tool_id))
                else:
                    results.append(info)
                continue
            results.append(info)
        return results
