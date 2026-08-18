# Design Document: eSim Automated Tool Manager

| Item | Detail |
|------|--------|
| Project | Automated Tool Manager for eSim |
| Task | eSim Semester Long Internship — Autumn 2026 — Screening Task 5 |
| Version | 1.2.2 |
| Language | Python 3.9+ |
| Platforms | Windows, Linux, macOS |

---

## 1. Problem statement

eSim relies on external tools such as KiCad, Ngspice, GHDL, Verilator, and a Python scientific stack. Installing and maintaining those tools by hand is error-prone: versions differ across machines, install paths vary by operating system, and missing dependencies break simulation workflows.

This project defines and implements an Automated Tool Manager that:

1. Installs tools in a version-aware, OS-aware manner  
2. Checks for and applies updates  
3. Configures environment variables and PATH for use with eSim  
4. Reports missing or incompatible dependencies  
5. Exposes a command-line interface and an optional graphical interface, with persistent action logs  

---

## 2. Scope

### In scope

- Catalog-driven management of eSim-related external tools  
- Install, update, configure, and dependency-check workflows  
- Package-manager integration where available  
- Portable archive install for Ngspice on Windows  
- CLI and GUI front ends  

### Out of scope

- Replacing the official eSim installer end-to-end  
- Building Ngspice or KiCad from source on every host  
- Silent privilege escalation (sudo / UAC remain under OS control)  

---

## 3. Overall architecture

```
┌─────────────────────────────────────────────────────────────┐
│                 CLI (esim-tm)  ·  Tkinter GUI                │
└────────────────────────────┬────────────────────────────────┘
                             │
┌────────────────────────────▼────────────────────────────────┐
│                        ToolManager                           │
│         orchestration / public API for all operations        │
└──┬─────────┬─────────┬──────────┬──────────┬────────────────┘
   ▼         ▼         ▼          ▼          ▼
Installer  Updater  Config    Dependency  Version
                      Handler   Checker     Probe
   └─────────┴─────────┴──────────┴──────────┘
                             │
              config/tools.yaml  ·  persistent state
                             │
   winget / choco / scoop / apt / dnf / brew / pip / archive / local bundle
```

Design choices:

| Choice | Rationale |
|--------|-----------|
| Catalog in YAML | New tools and versions can be added without rewriting core logic |
| Separate modules per concern | Installation, updates, configuration, and dependency checks stay independently testable |
| Dry-run mode | Privileged package installs can be previewed safely |
| Dual proof path | `demo-tool` exercises the full pipeline offline; Ngspice demonstrates a real external tool install |

---

## 4. Module breakdown

| Module | Path | Responsibility |
|--------|------|----------------|
| CLI | `esim_toolmanager/cli.py` | Argument parsing and user-facing commands |
| GUI | `esim_toolmanager/gui.py` | Tkinter interface for the same operations |
| ToolManager | `esim_toolmanager/core/manager.py` | Orchestrates subsystems |
| ToolInstaller | `esim_toolmanager/core/installer.py` | Package-manager, archive, and local-bundle installs; state |
| Archive install | `esim_toolmanager/core/archive_install.py` | Download and extract portable archives |
| ToolUpdater | `esim_toolmanager/core/updater.py` | Update detection and application |
| PM query | `esim_toolmanager/core/pm_query.py` | Remote version lookup via winget / brew / apt |
| ConfigurationHandler | `esim_toolmanager/core/config_handler.py` | Env vars, PATH, activation scripts, bridge JSON |
| Dependency checker | `esim_toolmanager/core/dependency.py` | Host and Python dependency evaluation |
| Version utilities | `esim_toolmanager/core/version.py` | Binary discovery and version comparison |
| Platform utilities | `esim_toolmanager/core/platform_utils.py` | OS detection, package-manager discovery, install plans |
| Tool catalog | `config/tools.yaml` | Preferred versions, packages, search paths, dependencies |
| Logging / paths | `esim_toolmanager/utils/` | Rotating logs and path helpers |

---

## 5. Component interaction

### 5.1 Installation

1. Resolve the tool entry from `config/tools.yaml`.  
2. Run an informational dependency check.  
3. Select an install strategy:  
   - `python-deps` → `pip`  
   - `local_bundle` → managed demo binary  
   - existing compatible binary on the system → adopt and configure  
   - OS package manager command when a matching manager is available  
   - portable archive (Ngspice on Windows) when configured  
4. Probe the installed version.  
5. Apply configuration and write install state under `~/.esim_toolmanager/`.

### 5.2 Version checking

1. Locate binaries on PATH and in OS-specific search directories.  
2. Run the tool with catalog `version_args` and parse output with `version_regex`.  
3. Classify status: `ok`, `outdated`, `incompatible`, `not_installed`, or `partial` (Python meta-package).

### 5.3 Updates

1. Determine the available version from the catalog preferred version and, when possible, live package-manager queries.  
2. Compare with the installed version.  
3. On update, reinstall with `force=True` and report previous and new versions.

### 5.4 Configuration

1. Resolve the tool home: if the discovered binary lives in a `bin` folder, the home is the parent of `bin` so catalog templates like `{install_path}/bin` stay correct.  
2. Render path and environment templates from the catalog.  
3. Write `esim_tools.env`, path JSON, per-tool JSON, and `esim_bridge.json`.  
4. Write activation helpers for bash/zsh (`activate.sh`), PowerShell (`activate.ps1`), and CMD (`activate.bat`).  
5. `esim_bridge.json` includes `env_vars`, `path_by_tool`, and a `tools` map with `install_path`, `binary`, and `version` when known.  
6. Uninstall removes that tool’s unique environment keys and rewrites the bridge.

### 5.5 Dependency checking

1. Check host prerequisites (supported OS family, Python ≥ 3.9, pip).  
2. Check declared system binaries and Python requirements.  
3. Report missing or incompatible items with remediation text.

### 5.6 User interface and logging

- CLI exposes list, status, install, uninstall, update, configure, deps, plan, verify, doctor, log, and gui.  
- GUI mirrors those actions (Force checkbox, Uninstall with confirm).  
- `deps` exits non-zero when any check fails.  
- Actions are written to `logs/tool_manager.log`.

---

## 6. Requirement coverage

| Requirement | Implementation summary |
|-------------|------------------------|
| Tool Installation Management | Package managers, portable Ngspice archive, adopt-existing, version recording |
| Update and Upgrade System | Catalog comparison, remote PM queries, update apply path |
| Configuration Handling | Env/PATH files, multi-shell activation, eSim bridge JSON |
| Dependency Checker | Host + Python checks with user-visible feedback |
| User Interface | CLI, GUI, action log |
| Cross-platform / package managers (optional) | Windows, Linux, macOS plans; winget, apt, brew, and related managers |

---

## 7. Platform support

| Concern | Windows | Linux | macOS |
|---------|---------|-------|-------|
| Package managers | winget, Chocolatey, Scoop | apt, dnf, pacman, zypper, flatpak | Homebrew |
| Binary search | PATH, Program Files, KiCad versioned bins | PATH, `/usr`, `/usr/local`, snap/flatpak exports | PATH, Homebrew prefixes, KiCad.app |
| Activation | `activate.ps1`, `activate.bat` | `activate.sh` | `activate.sh` |
| Install plan | `plan` lists commands for all three OS families on any host | same | same |

---

## 8. Persistent state

| Artifact | Location |
|----------|----------|
| Install state | `~/.esim_toolmanager/.esim_tm_state.json` |
| Configuration and activation | `~/.esim_toolmanager/config/` |
| eSim bridge | `~/.esim_toolmanager/config/esim_bridge.json` |
| Action log | `<repository>/logs/tool_manager.log` |
| Tool catalog | `<repository>/config/tools.yaml` |

---

## 9. Testing approach

- Unit tests for version parsing, package-manager command construction, and dependency evaluation  
- Integration tests for demo-tool install / configure / uninstall and update detection  
- Cross-platform plan tests ensuring Windows, Linux, and Darwin entries exist  
- `verify` command for an end-to-end self-check on the current host  

```bash
python -m pytest -q
python -m esim_toolmanager verify
```

---

## 10. Security considerations

- Subprocesses are invoked with argument lists (no shell interpolation).  
- Uninstall removes only trees under the manager install root.  
- Dry-run does not persist package-manager installs.  
- Activation scripts quote environment values appropriately per shell.  
- Archive downloads stream to disk (urllib, then curl fallback), try catalog mirrors, and reject HTML/truncated files.

---

## 11. Python dependency pins (eSim 2.5)

`python-deps` in `config/tools.yaml` lists the official eSim 2.5 pins (`numpy==1.24.4`, `scipy==1.10.1`, `matplotlib==3.7.5`, …) under `dependencies.python`. Those wheels stop at Python 3.11.

On Python 3.12+ the manager automatically switches to `dependencies.python_compat` (installable newer specs). `deps` records this as an informational, satisfied platform note — it does not fail the host just because the interpreter is 3.12. Missing packages are still reported as missing. The manager itself runs on Python 3.9+.

---

## 12. Summary

The Automated Tool Manager is a modular, catalog-driven Python system for managing eSim’s external toolchain. The prototype demonstrates installation and version checking, and also provides update, configuration, dependency checking, and user-interface capabilities suitable for screening evaluation and further integration with eSim.
