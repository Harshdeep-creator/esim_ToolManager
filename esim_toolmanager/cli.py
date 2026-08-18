"""Command-line interface for the eSim Automated Tool Manager."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from typing import List, Optional

from esim_toolmanager import __version__
from esim_toolmanager.core.manager import ToolManager


def _configure_stdio() -> None:
    """Prefer UTF-8 on Windows consoles; never crash on unsupported glyphs."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            pass


def _print_table(rows: List[dict], columns: List[str]) -> None:
    if not rows:
        print("(no tools)")
        return
    widths = {c: len(c) for c in columns}
    for row in rows:
        for c in columns:
            widths[c] = max(widths[c], len(str(row.get(c, ""))))
    header = "  ".join(c.upper().ljust(widths[c]) for c in columns)
    print(header)
    print("  ".join("-" * widths[c] for c in columns))
    for row in rows:
        print("  ".join(str(row.get(c, "")).ljust(widths[c]) for c in columns))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="esim-tm",
        description=(
            "eSim Automated Tool Manager - install, update, configure, and "
            "verify external tools (Ngspice, KiCad, GHDL, ...) on Windows, Linux, and macOS."
        ),
    )
    parser.add_argument(
        "--version", action="version", version=f"eSim Tool Manager {__version__}"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show actions without executing package-manager installs",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="Emit machine-readable JSON where applicable",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Enable debug logging"
    )

    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="List catalog tools and detected versions")

    p_status = sub.add_parser("status", help="Show version status for tools")
    p_status.add_argument("tool", nargs="?", help="Optional tool id")

    p_install = sub.add_parser("install", help="Install a tool")
    p_install.add_argument("tool", help="Tool id (or 'required' for all required tools)")
    p_install.add_argument(
        "--force", action="store_true", help="Reinstall even if already present"
    )

    p_uninstall = sub.add_parser("uninstall", help="Uninstall a managed tool")
    p_uninstall.add_argument("tool", help="Tool id")

    p_update = sub.add_parser("update", help="Update a tool (or check updates)")
    p_update.add_argument("tool", nargs="?", help="Tool id (omit with --check/--all)")
    p_update.add_argument(
        "--check", action="store_true", help="Only check for available updates"
    )
    p_update.add_argument(
        "--all", action="store_true", help="Update all tools with available updates"
    )
    p_update.add_argument(
        "--force", action="store_true", help="Force reinstall/upgrade"
    )

    p_config = sub.add_parser("configure", help="Apply path/env configuration")
    p_config.add_argument("tool", nargs="?", help="Tool id (omit for all)")

    p_deps = sub.add_parser("deps", help="Check dependencies (host + tools)")
    p_deps.add_argument("tool", nargs="?", help="Optional tool id")

    p_plan = sub.add_parser(
        "plan",
        help="Show install commands for Windows, Linux, and macOS (no execution)",
    )
    p_plan.add_argument("tool", nargs="?", help="Optional tool id")

    sub.add_parser(
        "verify",
        help="Run end-to-end self-check (install/version/configure/update/deps)",
    )
    sub.add_parser("doctor", help="Full environment health report")
    sub.add_parser("activate-help", help="Show how to activate managed environment")

    p_log = sub.add_parser("log", help="Show recent action log entries")
    p_log.add_argument("-n", type=int, default=40, help="Number of lines (default 40)")

    sub.add_parser("gui", help="Launch simple graphical interface")

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    _configure_stdio()
    parser = build_parser()
    args = parser.parse_args(argv)

    level = logging.DEBUG if args.verbose else logging.INFO
    mgr = ToolManager(dry_run=args.dry_run, log_level=level)

    try:
        return _dispatch(mgr, args)
    except KeyError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001
        print(f"Error: {exc}", file=sys.stderr)
        if args.verbose:
            raise
        return 1


def _dispatch(mgr: ToolManager, args: argparse.Namespace) -> int:
    if args.command == "list":
        rows = mgr.list_tools()
        if args.as_json:
            print(json.dumps(rows, indent=2))
        else:
            _print_table(
                rows,
                [
                    "id",
                    "name",
                    "status",
                    "installed_version",
                    "preferred_version",
                    "required",
                ],
            )
        return 0

    if args.command == "status":
        if args.tool:
            info = mgr.check_version(args.tool)
            data = info.__dict__
            if args.as_json:
                print(json.dumps(data, indent=2, default=str))
            else:
                print(f"Tool:      {info.tool_id}")
                print(f"Installed: {info.installed}")
                print(f"Version:   {info.version or '-'}")
                print(f"Path:      {info.binary_path or '-'}")
                print(f"Status:    {info.status}")
                print(f"Message:   {info.message}")
        else:
            infos = [v.__dict__ for v in mgr.check_all_versions()]
            if args.as_json:
                print(json.dumps(infos, indent=2, default=str))
            else:
                _print_table(
                    infos,
                    ["tool_id", "status", "version", "preferred_version", "message"],
                )
        return 0

    if args.command == "install":
        if args.tool == "required":
            results = mgr.install_required()
        else:
            results = [mgr.install(args.tool, force=args.force)]
        payload = [r.__dict__ for r in results]
        if args.as_json:
            print(json.dumps(payload, indent=2))
        else:
            for r in results:
                mark = "OK" if r.success else "FAIL"
                print(f"[{mark}] {r.tool_id} via {r.method}: {r.message}")
                if r.install_path:
                    print(f"       path: {r.install_path}")
        return 0 if all(r.success for r in results) else 1

    if args.command == "uninstall":
        r = mgr.uninstall(args.tool)
        if args.as_json:
            print(json.dumps(r.__dict__, indent=2))
        else:
            print(("OK" if r.success else "FAIL") + f": {r.message}")
        return 0 if r.success else 1

    if args.command == "update":
        if args.check or (args.tool is None and not args.all):
            updates = mgr.check_updates()
            rows = [u.__dict__ for u in updates]
            if args.as_json:
                print(json.dumps(rows, indent=2))
            else:
                _print_table(
                    [
                        {
                            "tool_id": u["tool_id"],
                            "status": u["status"],
                            "current": u.get("current_version"),
                            "available": u.get("available_version"),
                            "source": u.get("remote_source"),
                            "message": u.get("message"),
                        }
                        for u in rows
                    ],
                    [
                        "tool_id",
                        "status",
                        "current",
                        "available",
                        "source",
                        "message",
                    ],
                )
            return 0
        if args.all:
            results = mgr.update_all()
        else:
            if not args.tool:
                print("Error: specify a tool, or use --check / --all", file=sys.stderr)
                return 2
            results = [mgr.update(args.tool, force=args.force)]
        rows = [u.__dict__ for u in results]
        if args.as_json:
            print(json.dumps(rows, indent=2))
        else:
            for u in results:
                prev = u.get("previous_version")
                new = u.get("new_version")
                trail = f" ({prev} -> {new})" if prev or new else ""
                print(f"{u['tool_id']}: {u['status']} - {u['message']}{trail}")
        return 0 if all(u["status"] != "failed" for u in results) else 1

    if args.command == "configure":
        if args.tool:
            results = [mgr.configure(args.tool)]
        else:
            results = mgr.configure_all()
        if args.as_json:
            print(json.dumps(results, indent=2))
        else:
            for r in results:
                print(f"{r['tool_id']}: {r['message']}")
                for f in r.get("files_written") or []:
                    print(f"  wrote {f}")
            print()
            print(mgr.activation_help())
        return 0

    if args.command == "deps":
        reports = mgr.check_dependencies(args.tool)
        if args.as_json:
            print(
                json.dumps(
                    [
                        {
                            "tool_id": r.tool_id,
                            "ok": r.ok,
                            "partial": r.partial,
                            "results": [x.__dict__ for x in r.results],
                        }
                        for r in reports
                    ],
                    indent=2,
                    default=str,
                )
            )
        else:
            print(mgr.dependency_summary(args.tool))
        return 0 if all(r.ok for r in reports) else 1

    if args.command == "plan":
        plans = mgr.plan(args.tool)
        if args.as_json:
            print(json.dumps(plans, indent=2))
        else:
            for plan in plans:
                print(f"\n=== Plan: {plan['tool_id']} ({plan.get('display_name')}) ===")
                print(f"Preferred version: {plan.get('preferred_version')}")
                print(
                    f"Current host: {plan.get('current_platform')} | "
                    f"PMs: {', '.join(plan.get('available_package_managers') or []) or 'none'}"
                )
                matrix = plan.get("matrix") or {}
                for os_name in ("windows", "linux", "darwin"):
                    print(f"\n[{os_name}]")
                    os_plan = matrix.get(os_name) or {}
                    if not os_plan:
                        print("  (no packaged install defined)")
                        continue
                    for pm, cmd in os_plan.items():
                        if isinstance(cmd, list):
                            print(f"  {pm}: {' '.join(cmd)}")
                        else:
                            print(f"  {pm}: {cmd}")
        return 0

    if args.command == "verify":
        report = mgr.verify()
        if args.as_json:
            print(json.dumps(report, indent=2))
        else:
            print("=== eSim Tool Manager Verify ===")
            print(
                f"Platform: {report['platform']['system']} | "
                f"Overall: {'PASS' if report['overall_ok'] else 'FAIL'}"
            )
            for step in report["steps"]:
                mark = "OK" if step["ok"] else "FAIL"
                print(f"[{mark}] {step['step']}: {step['detail']}")
        return 0 if report["overall_ok"] else 1

    if args.command == "doctor":
        report = mgr.doctor()
        if args.as_json:
            print(json.dumps(report, indent=2))
        else:
            print("=== eSim Tool Manager Doctor ===")
            print(
                f"Manager: {report['manager_version']} | "
                f"Platform: {report['platform']['system']} "
                f"{report['platform']['release']}"
            )
            print(f"Install root: {report['install_root']}")
            print(
                "Package managers: "
                + (", ".join(report["platform"]["available_package_managers"]) or "none")
            )
            print("\n-- Versions --")
            _print_table(
                report["versions"],
                ["tool_id", "status", "version", "preferred_version", "message"],
            )
            print("\n-- Dependencies --")
            print(report["dependencies"])
            print("\n-- Activation --")
            print(report["activation"])
            print("\n-- Cross-platform install plans (sample: ngspice) --")
            ng = (report.get("install_plans") or {}).get("ngspice") or {}
            matrix = ng.get("matrix") or {}
            for os_name in ("windows", "linux", "darwin"):
                pms = ", ".join((matrix.get(os_name) or {}).keys()) or "none"
                print(f"  {os_name}: {pms}")
            print("  (full commands: esim-tm plan ngspice)")
        return 0

    if args.command == "activate-help":
        print(mgr.activation_help())
        return 0

    if args.command == "log":
        print(mgr.read_log_tail(args.n))
        return 0

    if args.command == "gui":
        try:
            from esim_toolmanager.gui import launch_gui
        except Exception as exc:  # noqa: BLE001
            print(
                "GUI unavailable: Tkinter is not installed or cannot be imported.",
                file=sys.stderr,
            )
            print(f"Details: {exc}", file=sys.stderr)
            print("Use the CLI instead, for example: esim-tm list", file=sys.stderr)
            return 1
        try:
            launch_gui(mgr)
            return 0
        except Exception as exc:  # noqa: BLE001
            print(f"GUI unavailable: {exc}", file=sys.stderr)
            print("Use the CLI instead, for example: esim-tm list", file=sys.stderr)
            return 1

    parser = build_parser()
    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
