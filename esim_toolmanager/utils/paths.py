"""Path helpers for config, state, and logs."""

from __future__ import annotations

import os
from pathlib import Path


def get_project_root() -> Path:
    """Return repository root (parent of the package directory)."""
    return Path(__file__).resolve().parents[2]


def get_config_path() -> Path:
    """Return path to tools.yaml (override with ESIM_TM_CONFIG)."""
    override = os.environ.get("ESIM_TM_CONFIG")
    if override:
        return Path(override).expanduser().resolve()
    return get_project_root() / "config" / "tools.yaml"


def get_install_root() -> Path:
    """Directory where Tool Manager installs managed tools."""
    override = os.environ.get("ESIM_TM_HOME")
    if override:
        return Path(override).expanduser().resolve()
    return Path.home() / ".esim_toolmanager"


def get_state_path() -> Path:
    """Persistent JSON state file for installed tools."""
    return get_install_root() / ".esim_tm_state.json"


def get_log_dir() -> Path:
    """Log directory under the project (or ESIM_TM_LOG_DIR)."""
    override = os.environ.get("ESIM_TM_LOG_DIR")
    if override:
        return Path(override).expanduser().resolve()
    return get_project_root() / "logs"


def install_home_from_binary(binary_path: Path) -> Path:
    """Map a discovered executable to the tool home used in catalog templates.

    Catalog entries use ``{install_path}/bin``. If we stored the binary's
    parent (already a ``bin`` folder), templates would produce ``.../bin/bin``.
    """
    path = Path(binary_path)
    parent = path.parent
    if parent.name.lower() in {"bin", "sbin"}:
        return parent.parent
    return parent


def normalize_install_home(install_path: Path) -> Path:
    """If a recorded home is already a bin directory, step up one level."""
    path = Path(install_path)
    if path.name.lower() in {"bin", "sbin"}:
        return path.parent
    return path
