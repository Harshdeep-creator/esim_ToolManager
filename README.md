# eSim Automated Tool Manager

Python prototype that installs, updates, configures, and verifies external tools used by [eSim](https://github.com/FOSSEE/eSim) (Ngspice, KiCad, GHDL, Verilator, and related Python packages).

| Deliverable | Location |
|-------------|----------|
| Design document | [`docs/DESIGN.md`](docs/DESIGN.md) |
| Source code | [`esim_toolmanager/`](esim_toolmanager/), [`config/tools.yaml`](config/tools.yaml) |
| Instructions for execution | This file |
| Presentation outline (optional) | [`docs/PRESENTATION.md`](docs/PRESENTATION.md) |

---

## What this project implements

The screening task requires any two of the listed requirements. This repository implements all of them:

1. **Tool installation management** — download/install via package managers or portable archive; version detection after install  
2. **Update and upgrade** — compare installed vs preferred/remote versions; update with limited manual steps  
3. **Configuration handling** — environment variables, PATH entries, shell activation scripts, eSim bridge JSON  
4. **Dependency checker** — host and Python dependency reports with remediation text  
5. **User interface** — CLI (`esim-tm` / `python -m esim_toolmanager`) and optional Tkinter GUI; action log file  

Optional features: Windows / Linux / macOS install plans; integration with winget, Chocolatey, Scoop, apt, dnf, pacman, zypper, flatpak, Homebrew, and pip.

Environment overrides: `ESIM_TM_HOME` (install/state root), `ESIM_TM_CONFIG` (catalog path), `ESIM_TM_LOG_DIR`.

Demo video (optional deliverable): [`docs/demo/esim_toolmanager_demo.mp4`](docs/demo/esim_toolmanager_demo.mp4)

---

## Prerequisites

- Python 3.9 or newer  
- `pip`  
- Optional: OS package manager for system EDA packages (winget/Chocolatey/Scoop, apt/dnf/…, Homebrew)

Python package dependencies of this manager:

```text
PyYAML>=6.0
packaging>=23.0
py7zr>=0.20.0
```

---

## Installation

```bash
git clone <repository-url> esim_ToolManager
cd esim_ToolManager

python -m venv .venv
```

Activate the virtual environment:

```powershell
# Windows PowerShell
.\.venv\Scripts\Activate.ps1
```

```bash
# Linux / macOS
source .venv/bin/activate
```

Install the tool manager:

```bash
python -m pip install -r requirements.txt
python -m pip install -e .
```

---

## How to run and test

### 1. Automated tests

```bash
python -m pip install pytest
python -m pytest -q
```

### 2. Installation and version checking (required prototype behaviour)

```bash
# Offline proof-of-concept tool (works on all platforms)
python -m esim_toolmanager install demo-tool --force
python -m esim_toolmanager status demo-tool

# Ngspice: portable official Windows archive, or OS package manager on Linux/macOS
python -m esim_toolmanager install ngspice --force
python -m esim_toolmanager status ngspice
```

### 3. Updates, configuration, dependencies, UI

```bash
python -m esim_toolmanager update --check
python -m esim_toolmanager configure ngspice
python -m esim_toolmanager deps
python -m esim_toolmanager list
python -m esim_toolmanager doctor
python -m esim_toolmanager log -n 40
python -m esim_toolmanager gui
```

### 4. Cross-platform install plans

Shows Windows, Linux, and macOS install commands from any host:

```bash
python -m esim_toolmanager plan ngspice
python -m esim_toolmanager plan kicad
```

### 5. Integrated self-check

```bash
python -m esim_toolmanager verify
```

---

## Activating configured tools

After `configure`, load the generated environment in a new shell:

```powershell
# Windows PowerShell
. "$HOME\.esim_toolmanager\config\activate.ps1"
```

```bash
# Linux / macOS
source ~/.esim_toolmanager/config/activate.sh
```

Generated files also include `activate.bat` and `esim_bridge.json` under `~/.esim_toolmanager/config/`.

---

## Command reference

| Command | Description |
|---------|-------------|
| `list` | List catalog tools and detected versions |
| `status [tool]` | Show version status |
| `install <tool>` | Install a tool (`demo-tool`, `ngspice`, `kicad`, …) |
| `uninstall <tool>` | Remove managed install state / local files |
| `update --check` | Check for updates |
| `update <tool>` | Update one tool |
| `configure [tool]` | Write environment and PATH configuration |
| `deps [tool]` | Dependency report |
| `plan [tool]` | Show install commands for Windows, Linux, and macOS |
| `verify` | End-to-end self-check |
| `doctor` | Environment summary |
| `log [-n N]` | Show recent log lines |
| `gui` | Open graphical interface |

Global options: `--dry-run`, `--json`, `-v`.

Entry points after install:

```bash
python -m esim_toolmanager <command>
esim-tm <command>
```

---

## Repository layout

```text
esim_ToolManager/
├── README.md                 # Instructions for execution
├── docs/DESIGN.md            # Design document
├── docs/PRESENTATION.md      # Optional presentation outline
├── docs/demo/                # Optional demo video
├── config/tools.yaml         # Tool catalog (versions, packages, paths)
├── esim_toolmanager/         # Application source
├── tests/
├── requirements.txt
└── pyproject.toml
```

Managed runtime data (created on the user machine, not in the repo):

```text
~/.esim_toolmanager/          # installs, state, config, activation scripts
logs/tool_manager.log         # action log under the repository
```

---

## Notes on tool installs

- **Ngspice (Windows):** installed from the official portable archive (`ngspice-46_64.7z`) via SourceForge mirrors when Chocolatey/Scoop are not available. Invalid HTML downloads are rejected and the next mirror is tried.  
- **Ngspice (Linux/macOS):** intended via apt/dnf/pacman/zypper or Homebrew (`plan` shows the commands).  
- **KiCad / GHDL (Windows):** winget package identifiers are used when winget is present.  
- **`--dry-run`:** prints the install command without changing the system package state.  
- **`python-deps`:** catalog official pins match eSim 2.5 (`numpy==1.24.4`, `scipy==1.10.1`) and are used on Python 3.10/3.11. On Python 3.12+ the manager switches to `python_compat` specs so `install python-deps` and `deps` do not fail because those wheels are unpublished. A satisfied note in `deps` explains the switch. The manager itself runs on Python 3.9+.  
- **`deps` exit code:** 0 if all reported checks pass, 1 if anything is missing or incompatible.
- **`gui`:** if Tk/display is unavailable, the command prints a CLI fallback message and exits 1 instead of crashing.

---

## License

GPL-3.0-or-later. See [`LICENSE`](LICENSE).
