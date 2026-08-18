"""Tkinter GUI for the eSim Tool Manager."""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk
from typing import TYPE_CHECKING, Callable, Optional

if TYPE_CHECKING:
    from esim_toolmanager.core.manager import ToolManager


STATUS_COLORS = {
    "ok": "#1b7a3d",
    "up_to_date": "#1b7a3d",
    "outdated": "#b36b00",
    "update_available": "#b36b00",
    "partial": "#b36b00",
    "incompatible": "#a12020",
    "not_installed": "#555555",
    "failed": "#a12020",
    "unknown": "#555555",
}


def launch_gui(manager: "ToolManager") -> None:
    try:
        root = tk.Tk()
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(
            "Cannot open GUI (no display or Tk backend). "
            "Use the CLI instead: esim-tm --help"
        ) from exc
    root.title("eSim Automated Tool Manager")
    root.geometry("1040x680")
    root.minsize(860, 520)

    style = ttk.Style()
    for theme in ("vista", "clam", "default"):
        if theme in style.theme_names():
            style.theme_use(theme)
            break

    outer = ttk.Frame(root, padding=12)
    outer.pack(fill=tk.BOTH, expand=True)

    header = ttk.Frame(outer)
    header.pack(fill=tk.X)
    ttk.Label(
        header,
        text="eSim Automated Tool Manager",
        font=("Segoe UI", 16, "bold"),
    ).pack(anchor=tk.W)
    ttk.Label(
        header,
        text=(
            f"Host: {manager.platform.system} {manager.platform.release} | "
            f"PMs: {', '.join(manager.platform.available_package_managers) or 'none'} | "
            "Install · Update · Configure · Deps · Plan · Verify"
        ),
        wraplength=980,
    ).pack(anchor=tk.W, pady=(2, 8))

    body = ttk.Panedwindow(outer, orient=tk.VERTICAL)
    body.pack(fill=tk.BOTH, expand=True)

    top = ttk.Frame(body)
    bottom = ttk.Frame(body)
    body.add(top, weight=3)
    body.add(bottom, weight=2)

    columns = ("id", "name", "status", "installed", "preferred", "update")
    tree = ttk.Treeview(top, columns=columns, show="headings", height=14)
    headings = {
        "id": "Tool ID",
        "name": "Name",
        "status": "Status",
        "installed": "Installed",
        "preferred": "Preferred",
        "update": "Update",
    }
    widths = {
        "id": 110,
        "name": 170,
        "status": 110,
        "installed": 90,
        "preferred": 90,
        "update": 120,
    }
    for col in columns:
        tree.heading(col, text=headings[col])
        tree.column(col, width=widths[col], anchor=tk.W)

    scroll = ttk.Scrollbar(top, orient=tk.VERTICAL, command=tree.yview)
    tree.configure(yscrollcommand=scroll.set)
    tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    scroll.pack(side=tk.RIGHT, fill=tk.Y)

    log_label = ttk.Label(bottom, text="Action log")
    log_label.pack(anchor=tk.W)
    log = scrolledtext.ScrolledText(bottom, height=12, state=tk.DISABLED, wrap=tk.WORD)
    log.pack(fill=tk.BOTH, expand=True, pady=(4, 0))

    def write_log(msg: str, tag: str = "info") -> None:
        log.configure(state=tk.NORMAL)
        log.insert(tk.END, msg + "\n", tag)
        log.see(tk.END)
        log.configure(state=tk.DISABLED)

    log.tag_configure("info", foreground="#222222")
    log.tag_configure("ok", foreground="#1b7a3d")
    log.tag_configure("warn", foreground="#b36b00")
    log.tag_configure("err", foreground="#a12020")

    force_var = tk.BooleanVar(value=False)

    def selected_tool(*, required: bool = True) -> Optional[str]:
        sel = tree.selection()
        if not sel:
            if required:
                messagebox.showinfo("Select a tool", "Please select a tool in the list.")
            return None
        return tree.item(sel[0], "values")[0]

    def safe(fn: Callable[[], None]) -> Callable[[], None]:
        def wrap() -> None:
            try:
                fn()
            except Exception as exc:  # noqa: BLE001
                write_log(str(exc), "err")
                messagebox.showerror("Error", str(exc))

        return wrap

    def refresh(*, log_refresh: bool = True) -> None:
        for item in tree.get_children():
            tree.delete(item)
        updates = {u.tool_id: u for u in manager.check_updates(query_remote=False)}
        seen_status = set()
        for row in manager.list_tools():
            u = updates.get(row["id"])
            update_txt = u.status if u else "-"
            status = str(row["status"])
            if status not in seen_status:
                tree.tag_configure(status, foreground=STATUS_COLORS.get(status, "#333333"))
                seen_status.add(status)
            item = tree.insert(
                "",
                tk.END,
                values=(
                    row["id"],
                    row["name"],
                    row["status"],
                    row["installed_version"] or "-",
                    row["preferred_version"] or "-",
                    update_txt,
                ),
            )
            tree.item(item, tags=(status,))
        if log_refresh:
            write_log("Refreshed tool list and update status.", "ok")

    def do_install() -> None:
        tool = selected_tool()
        if not tool:
            return
        result = manager.install(tool, force=force_var.get())
        tag = "ok" if result.success else "err"
        write_log(
            f"Install {tool}: {'OK' if result.success else 'FAIL'} "
            f"via {result.method} - {result.message}",
            tag,
        )
        refresh(log_refresh=False)

    def do_uninstall() -> None:
        tool = selected_tool()
        if not tool:
            return
        if not messagebox.askyesno(
            "Uninstall",
            f"Remove managed state for '{tool}'? Package-manager system packages are not purged.",
        ):
            return
        result = manager.uninstall(tool)
        tag = "ok" if result.success else "err"
        write_log(f"Uninstall {tool}: {result.message}", tag)
        refresh(log_refresh=False)

    def do_update_check() -> None:
        write_log("Checking updates (may query package managers)...", "info")
        for u in manager.check_updates(query_remote=True):
            tag = "warn" if u.update_available else "ok"
            extra = f" [{u.remote_source}]" if u.remote_source else ""
            write_log(
                f"Update {u.tool_id}: {u.status} - {u.message}{extra}",
                tag,
            )
        refresh(log_refresh=False)

    def do_update() -> None:
        tool = selected_tool()
        if not tool:
            return
        info = manager.update(tool, force=force_var.get())
        tag = "ok" if info.status != "failed" else "err"
        write_log(f"Update {tool}: {info.status} - {info.message}", tag)
        refresh(log_refresh=False)

    def do_configure() -> None:
        tool = selected_tool()
        if not tool:
            return
        result = manager.configure(tool)
        write_log(f"Configure {tool}: {result['message']}", "ok")
        write_log(manager.activation_help(), "info")

    def do_deps() -> None:
        tool = selected_tool(required=False)
        write_log(manager.dependency_summary(tool), "info")

    def do_plan() -> None:
        tool = selected_tool()
        if not tool:
            return
        plan = manager.plan(tool)[0]
        write_log(
            f"Plan for {tool} (preferred {plan.get('preferred_version')}):",
            "info",
        )
        for os_name in ("windows", "linux", "darwin"):
            os_plan = (plan.get("matrix") or {}).get(os_name) or {}
            write_log(f"  [{os_name}]", "info")
            if not os_plan:
                write_log("    (none)", "warn")
            for pm, cmd in os_plan.items():
                text = " ".join(cmd) if isinstance(cmd, list) else str(cmd)
                write_log(f"    {pm}: {text}", "info")

    def do_status() -> None:
        tool = selected_tool()
        if not tool:
            return
        info = manager.check_version(tool)
        write_log(
            f"Status {tool}: {info.status} | version={info.version} | path={info.binary_path}",
            "ok" if info.status == "ok" else "warn",
        )

    def do_verify() -> None:
        write_log("Running verify (this may take a few seconds)...", "info")
        report = manager.verify()
        tag = "ok" if report["overall_ok"] else "err"
        write_log(
            f"Verify overall: {'PASS' if report['overall_ok'] else 'FAIL'} "
            f"on {report['platform']['system']}",
            tag,
        )
        for step in report["steps"]:
            write_log(
                f"  [{'OK' if step['ok'] else 'FAIL'}] {step['step']}: {step['detail']}",
                "ok" if step["ok"] else "err",
            )
        refresh(log_refresh=False)

    def do_doctor() -> None:
        report = manager.doctor()
        write_log(
            f"Doctor | platform={report['platform']['system']} | "
            f"PMs={', '.join(report['platform']['available_package_managers']) or 'none'}",
            "info",
        )
        for v in report["versions"]:
            write_log(
                f"  {v['tool_id']}: {v['status']} ({v.get('version') or '-'})",
                "ok" if v["status"] == "ok" else "warn",
            )

    def do_log() -> None:
        write_log("--- log file tail ---", "info")
        write_log(manager.read_log_tail(30), "info")

    buttons = ttk.Frame(outer)
    buttons.pack(fill=tk.X, pady=(10, 0))
    actions = [
        ("Refresh", lambda: refresh()),
        ("Status", do_status),
        ("Install", do_install),
        ("Uninstall", do_uninstall),
        ("Update check", do_update_check),
        ("Update", do_update),
        ("Configure", do_configure),
        ("Deps", do_deps),
        ("Plan", do_plan),
        ("Verify", do_verify),
        ("Doctor", do_doctor),
        ("Log", do_log),
    ]
    for text, cmd in actions:
        ttk.Button(buttons, text=text, command=safe(cmd)).pack(side=tk.LEFT, padx=2)
    ttk.Checkbutton(buttons, text="Force", variable=force_var).pack(side=tk.LEFT, padx=8)

    refresh()
    root.mainloop()
