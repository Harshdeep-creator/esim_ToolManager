"""Configuration handling: env vars, PATH, and eSim-friendly settings files."""

from __future__ import annotations

import json
import os
import shlex
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from esim_toolmanager.core.platform_utils import normalize_system
from esim_toolmanager.utils.logger import get_logger
from esim_toolmanager.utils.paths import get_install_root

logger = get_logger("config")


@dataclass
class ConfigResult:
    tool_id: str
    success: bool
    env_vars: Dict[str, str] = field(default_factory=dict)
    path_entries: List[str] = field(default_factory=list)
    files_written: List[str] = field(default_factory=list)
    message: str = ""


def _bash_quote(value: str) -> str:
    return shlex.quote(value)


def _ps_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _bat_value(value: str) -> str:
    """Escape a value for `set "KEY=value"` in CMD."""
    return value.replace("%", "%%")


class ConfigurationHandler:
    """Apply and persist tool configuration for seamless eSim integration."""

    def __init__(self, install_root: Optional[Path] = None) -> None:
        self.install_root = install_root or get_install_root()
        self.config_dir = self.install_root / "config"
        self.env_file = self.config_dir / "esim_tools.env"
        self.path_file = self.config_dir / "esim_tools_path.json"
        self.esim_bridge = self.config_dir / "esim_bridge.json"
        self.config_dir.mkdir(parents=True, exist_ok=True)

    def _format(self, template: str, install_path: Path) -> str:
        # Keep forward slashes in templates for portability; Path normalizes later
        return template.format(
            install_path=str(install_path).replace("\\", "/"),
            install_root=str(self.install_root).replace("\\", "/"),
            home=str(Path.home()).replace("\\", "/"),
        )

    def apply_tool_config(
        self,
        tool_id: str,
        install_path: Path,
        config_spec: Dict,
        *,
        activate_in_process: bool = True,
        runtime: Optional[Dict] = None,
    ) -> ConfigResult:
        """Write env/path configuration for a tool and optionally apply in-process."""
        env_vars: Dict[str, str] = {}
        path_entries: List[str] = []
        files: List[str] = []

        raw_env = (config_spec or {}).get("env_vars") or {}
        for key, value in raw_env.items():
            env_vars[key] = str(Path(self._format(str(value), install_path)))

        for entry in (config_spec or {}).get("path_append") or []:
            rendered = self._format(str(entry), install_path)
            path_entries.append(str(Path(rendered)))

        existing_env = self._read_env_file()
        existing_env.update(env_vars)
        self._write_env_file(existing_env)
        files.append(str(self.env_file))

        path_map = self._read_path_file()
        path_map[tool_id] = path_entries
        self.path_file.write_text(json.dumps(path_map, indent=2), encoding="utf-8")
        files.append(str(self.path_file))

        tool_cfg = self.config_dir / f"{tool_id}.json"
        tool_payload = {
            "tool_id": tool_id,
            "install_path": str(install_path),
            "env_vars": env_vars,
            "path_append": path_entries,
        }
        if runtime:
            if runtime.get("binary"):
                tool_payload["binary"] = runtime["binary"]
            if runtime.get("version"):
                tool_payload["version"] = runtime["version"]
            if runtime.get("status"):
                tool_payload["status"] = runtime["status"]
        tool_cfg.write_text(
            json.dumps(tool_payload, indent=2),
            encoding="utf-8",
        )
        files.append(str(tool_cfg))

        bridge = self._write_esim_bridge(existing_env, path_map)
        files.append(str(bridge))

        if activate_in_process:
            for key, value in env_vars.items():
                os.environ[key] = value
            self._prepend_path(path_entries)

        # Always write activation helpers for Windows + Unix so the repo is
        # usable when copied across machines.
        self._write_activation_scripts(existing_env, path_map)
        files.extend(
            [
                str(self.config_dir / "activate.sh"),
                str(self.config_dir / "activate.ps1"),
                str(self.config_dir / "activate.bat"),
            ]
        )

        logger.info("Configured %s at %s", tool_id, install_path)
        return ConfigResult(
            tool_id=tool_id,
            success=True,
            env_vars=env_vars,
            path_entries=path_entries,
            files_written=sorted(set(files)),
            message=f"Configuration applied for {tool_id}",
        )

    def remove_tool_config(self, tool_id: str) -> None:
        """Drop a tool from path map, env keys unique to it, and rewrite scripts."""
        path_map = self._read_path_file()
        path_map.pop(tool_id, None)
        self.path_file.write_text(json.dumps(path_map, indent=2), encoding="utf-8")
        tool_cfg = self.config_dir / f"{tool_id}.json"
        dropped_keys: List[str] = []
        if tool_cfg.exists():
            try:
                data = json.loads(tool_cfg.read_text(encoding="utf-8"))
                dropped_keys = list((data.get("env_vars") or {}).keys())
            except json.JSONDecodeError:
                dropped_keys = []
            tool_cfg.unlink()
        env = self._read_env_file()
        kept_keys = self._env_keys_from_tool_files()
        for key in dropped_keys:
            if key not in kept_keys:
                env.pop(key, None)
        self._write_env_file(env)
        self._write_esim_bridge(env, path_map)
        self._write_activation_scripts(env, path_map)

    def _env_keys_from_tool_files(self) -> set:
        keys = set()
        for path in self.config_dir.glob("*.json"):
            if path.name in ("esim_bridge.json", "esim_tools_path.json"):
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            keys.update((data.get("env_vars") or {}).keys())
        return keys

    def _tool_records(self) -> Dict[str, Dict]:
        records: Dict[str, Dict] = {}
        for path in sorted(self.config_dir.glob("*.json")):
            if path.name in ("esim_bridge.json", "esim_tools_path.json"):
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            tid = data.get("tool_id") or path.stem
            records[tid] = data
        return records

    def _write_esim_bridge(self, env: Dict[str, str], path_map: Dict[str, List[str]]) -> Path:
        """Machine-readable config eSim or wrappers can consume on any OS."""
        tools = self._tool_records()
        payload = {
            "manager": "esim-toolmanager",
            "install_root": str(self.install_root),
            "env_vars": env,
            "path_by_tool": path_map,
            "path_entries": [p for entries in path_map.values() for p in entries],
            "tools": {
                tid: {
                    "install_path": rec.get("install_path"),
                    "binary": rec.get("binary"),
                    "version": rec.get("version"),
                    "env_vars": rec.get("env_vars") or {},
                }
                for tid, rec in tools.items()
            },
            "notes": {
                "windows": "Run config/activate.ps1 or activate.bat before launching eSim",
                "linux": "source config/activate.sh before launching eSim",
                "darwin": "source config/activate.sh (zsh/bash) before launching eSim",
            },
        }
        self.esim_bridge.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return self.esim_bridge

    def _prepend_path(self, entries: List[str]) -> None:
        current = os.environ.get("PATH", "")
        parts = [p for p in current.split(os.pathsep) if p]
        for entry in reversed(entries):
            if entry and entry not in parts:
                parts.insert(0, entry)
        os.environ["PATH"] = os.pathsep.join(parts)

    def activate_all(self) -> None:
        """Load persisted configuration into the current process."""
        env = self._read_env_file()
        for key, value in env.items():
            os.environ[key] = value
        path_map = self._read_path_file()
        entries: List[str] = []
        for tool_paths in path_map.values():
            entries.extend(tool_paths)
        self._prepend_path(entries)
        logger.info("Activated managed environment (%d vars)", len(env))

    def get_activation_instructions(self) -> str:
        """Return OS-appropriate activation instructions (all scripts always exist)."""
        system = normalize_system()
        bash = self.config_dir / "activate.sh"
        ps1 = self.config_dir / "activate.ps1"
        bat = self.config_dir / "activate.bat"
        bridge = self.esim_bridge
        lines = [
            "Activation scripts (written for all platforms):",
            f"  Bash/zsh : source '{bash}'",
            f"  PowerShell: . '{ps1}'",
            f"  CMD       : call \"{bat}\"",
            f"  eSim bridge JSON: {bridge}",
        ]
        if system == "windows":
            lines.insert(0, "Detected Windows - prefer PowerShell/CMD activation:")
        elif system == "darwin":
            lines.insert(0, "Detected macOS - prefer bash/zsh activation:")
        else:
            lines.insert(0, "Detected Linux - prefer bash activation:")
        return "\n".join(lines)

    def _read_env_file(self) -> Dict[str, str]:
        data: Dict[str, str] = {}
        if not self.env_file.exists():
            return data
        for line in self.env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            data[key.strip()] = value.strip().strip('"')
        return data

    def _write_env_file(self, env: Dict[str, str]) -> None:
        lines = ["# Generated by eSim Tool Manager - do not edit by hand"]
        for key, value in sorted(env.items()):
            lines.append(f'{key}="{value}"')
        self.env_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def _read_path_file(self) -> Dict[str, List[str]]:
        if not self.path_file.exists():
            return {}
        try:
            return json.loads(self.path_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}

    def _write_activation_scripts(
        self, env: Dict[str, str], path_map: Dict[str, List[str]]
    ) -> None:
        all_paths: List[str] = []
        for entries in path_map.values():
            all_paths.extend(entries)

        # Bash / zsh (Linux + macOS)
        bash_lines = [
            "#!/usr/bin/env bash",
            "# eSim Tool Manager environment (Linux/macOS)",
        ]
        for key, value in env.items():
            bash_lines.append(f"export {key}={_bash_quote(value)}")
        if all_paths:
            joined = ":".join(all_paths)
            bash_lines.append(f'export PATH="{joined}:$PATH"')
        (self.config_dir / "activate.sh").write_text(
            "\n".join(bash_lines) + "\n", encoding="utf-8"
        )

        # PowerShell (Windows; also usable on pwsh for macOS/Linux)
        ps_lines = ["# eSim Tool Manager environment (PowerShell)"]
        for key, value in env.items():
            ps_lines.append(f"$env:{key} = {_ps_quote(value)}")
        for entry in all_paths:
            ps_lines.append(f"$env:Path = {_ps_quote(entry)} + [IO.Path]::PathSeparator + $env:Path")
        (self.config_dir / "activate.ps1").write_text(
            "\n".join(ps_lines) + "\n", encoding="utf-8"
        )

        # CMD batch (Windows)
        bat_lines = ["@echo off", "REM eSim Tool Manager environment (CMD)"]
        for key, value in env.items():
            bat_lines.append(f'set "{key}={_bat_value(value)}"')
        for entry in all_paths:
            bat_lines.append(f'set "PATH={_bat_value(entry)};%PATH%"')
        (self.config_dir / "activate.bat").write_text(
            "\r\n".join(bat_lines) + "\r\n", encoding="utf-8"
        )
