# eSim Tool Manager

eSim depends on a bunch of outside tools (Ngspice, KiCad, GHDL, Verilator) plus a Python stack. Installing those by hand on Windows vs Linux vs macOS is messy, so this is a small Python manager that can install them, check versions, update, set PATH/env, and tell you what is missing.

Written for the FOSSEE eSim internship screening, Autumn 2026, Task 5.

If you only have a few minutes, do this after setup:

```
python -m esim_toolmanager install demo-tool --force
python -m esim_toolmanager status demo-tool
```

demo-tool is a tiny local binary the manager creates itself. No admin, no download. That is the reliable proof of install + version check. Ngspice/KiCad need winget, Chocolatey, apt, brew, or similar, so those can fail if your machine is locked down. Use `--dry-run` if you just want to see the command.

Design write-up: [docs/DESIGN.md](docs/DESIGN.md)  
Demo recording: [docs/demo/esim_toolmanager_demo.mp4](docs/demo/esim_toolmanager_demo.mp4)  
Slide outline: [docs/PRESENTATION.md](docs/PRESENTATION.md)


## What it does

- Install: package managers where they exist, portable Ngspice archive on Windows, or adopt a copy already on PATH
- Version check: find the binary, parse `--version` / `-v`, compare with the catalog
- Update: `update --check` then `update <tool>`
- Configure: writes env/PATH files and shell helpers so eSim can pick the tools up
- Deps: host Python/pip plus the packages listed for each tool, with a one-line fix if something is missing
- UI: CLI (`esim-tm` or `python -m esim_toolmanager`) and a Tkinter window. Actions go to `logs/tool_manager.log`

Catalog is `config/tools.yaml`. Adding a tool is mostly YAML, not a rewrite of the Python.

Works with winget, Chocolatey, Scoop, apt, dnf, pacman, zypper, flatpak, Homebrew, and pip. `plan ngspice` prints Windows, Linux, and macOS commands from whatever OS you are on.

Optional env vars if you do not want the default home directory:

- `ESIM_TM_HOME` — install / state root (default `~/.esim_toolmanager`)
- `ESIM_TM_CONFIG` — catalog path
- `ESIM_TM_LOG_DIR` — log folder


## Setup

Python 3.9 or newer, plus pip. A system package manager is optional.

```
git clone https://github.com/Harshdeep-creator/esim_ToolManager.git
cd esim_ToolManager
python -m venv .venv
```

Windows PowerShell:

```
.\.venv\Scripts\Activate.ps1
```

Linux / macOS:

```
source .venv/bin/activate
```

```
python -m pip install -r requirements.txt
python -m pip install -e .
```

Requirements are just PyYAML, packaging, and py7zr (for the Ngspice `.7z` on Windows).


## Run

Tests:

```
python -m pip install pytest
python -m pytest -q
```

Install + version (start here):

```
python -m esim_toolmanager install demo-tool --force
python -m esim_toolmanager status demo-tool
```

Ngspice if you want a real EDA tool. On Windows this may download the official portable archive. On Linux/macOS it uses the OS package manager. Add `--dry-run` to preview:

```
python -m esim_toolmanager install ngspice --dry-run
python -m esim_toolmanager install ngspice --force
python -m esim_toolmanager status ngspice
```

The rest:

```
python -m esim_toolmanager update --check
python -m esim_toolmanager configure demo-tool
python -m esim_toolmanager deps demo-tool
python -m esim_toolmanager list
python -m esim_toolmanager plan ngspice
python -m esim_toolmanager plan kicad
python -m esim_toolmanager doctor
python -m esim_toolmanager log -n 40
python -m esim_toolmanager verify
python -m esim_toolmanager gui
```

`verify` runs an end-to-end self-check on the current machine (uses demo-tool, no admin).

Same CLI as:

```
esim-tm <command>
```

Flags that work on most commands: `--dry-run`, `--json`, `-v`.


## After configure

New shell, then:

Windows PowerShell:

```
. "$HOME\.esim_toolmanager\config\activate.ps1"
```

Linux / macOS:

```
source ~/.esim_toolmanager/config/activate.sh
```

CMD: `call "%USERPROFILE%\.esim_toolmanager\config\activate.bat"`

Also written: `esim_bridge.json` in the same folder. That is the file you would point eSim at later.


## Command list

| command | what it does |
|---|---|
| `list` | catalog tools, installed version, status |
| `status [tool]` | one tool, or all if you omit the name |
| `install <tool>` | demo-tool, ngspice, kicad, ghdl, verilator, python-deps, or `required` |
| `uninstall <tool>` | managed files/state only, not a full apt/winget purge |
| `update --check` | compare installed vs catalog / package manager |
| `update <tool>` | apply update (`--all` also exists) |
| `configure [tool]` | env + PATH files |
| `deps [tool]` | missing / incompatible, with a suggested fix |
| `plan [tool]` | install commands for Windows, Linux, macOS |
| `verify` | self-check |
| `doctor` | environment dump |
| `log -n 40` | last lines of the action log |
| `gui` | Tkinter UI |

`deps` exits 1 if anything failed. That is normal if you have not installed the eSim Python packages yet. Run `deps demo-tool` if you only want the host + demo check.


## Notes I hit while testing

Ngspice on Windows: Chocolatey or Scoop if you have them, otherwise `ngspice-46_64.7z` from SourceForge. The downloader skips HTML junk pages and tries a couple of mirrors.

Ngspice on Linux/macOS: `plan ngspice` shows apt/dnf/pacman/zypper or `brew install ngspice`.

KiCad and GHDL on Windows go through winget when winget is there (`KiCad.KiCad`, and a GHDL package id).

`--dry-run` does not write package-manager installs into the state file.

python-deps: catalog pins match eSim 2.5 (`numpy==1.24.4`, `scipy==1.10.1`, …). Those wheels stop at Python 3.11. On 3.12 the manager switches to a compatible set so `install python-deps` is not a dead end. The manager itself is fine on 3.9+.

If `gui` has no Tk/display it prints that and exits 1. Use the CLI.

Uninstall will not `apt remove` / `winget uninstall` system packages. It only drops what this manager recorded.


## Layout

```
README.md              this file
docs/DESIGN.md         architecture
docs/PRESENTATION.md   video outline
docs/demo/             mp4 demo
config/tools.yaml      versions, packages, paths
esim_toolmanager/      source
tests/
requirements.txt
pyproject.toml
LICENSE
```

On your machine (not in git):

```
~/.esim_toolmanager/     installs, state, activate scripts, esim_bridge.json
logs/tool_manager.log    created when you run the CLI
```


## License

GPL-3.0-or-later, see LICENSE.
