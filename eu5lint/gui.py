"""Simple desktop window for eu5lint.

Run with:  python -m eu5lint.gui
Bundled exe build (no installer, single portable file):
    pyinstaller --onefile --noconsole --name "EU5 Mod Checker" ^
        --collect-submodules eu5lint -p . eu5lint\\gui.py

Stdlib only (tkinter), so the exe stays small and dependency-free.
"""

from __future__ import annotations

import json
import threading
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .cli import find_vanilla
from .engine import run

MOD_DIR = Path.home() / "Documents/Paradox Interactive/Europa Universalis V/mod"

SEVERITY_LABEL = {"error": "Problem", "warning": "Warning", "info": "Note"}

# Plain-language explanation per rule, shown when a finding is clicked.
RULE_HELP = {
    "E001": "This advance links to another advance that is defined further "
            "down in the same file. The game reads files top to bottom, so "
            "the link silently fails. Fix: move the linked advance above "
            "this one, or the generator that writes the file must sort them.",
    "E002": "A tech tree can only hang from a root advance (one with no "
            "parents). This one hangs from a non-root, so everything "
            "attached to it silently detaches. Fix: point in_tree_of at a "
            "root advance.",
    "E003": "Auto modifier files must not contain game_data blocks or "
            "location-only keys. The game rejects them quietly and the "
            "modifier does nothing. Fix: use the static modifier system "
            "for location-scaled effects.",
    "E004": "The game only applies static modifier blocks whose names it "
            "already knows. This block name is invented, so it loads and "
            "does nothing. Fix: put the values inside an existing vanilla "
            "block instead.",
    "E005": "This defines file is missing the UTF-8 BOM marker. The game "
            "still loads it but logs a warning. Fix: save the file as "
            "UTF-8 with BOM.",
    "E006": "A quoted localization string contains a real line break, "
            "which cuts the string in half. Fix: replace the line break "
            "with the two characters \\n.",
    "E007": "This file re-declares a static modifier block that vanilla "
            "already has. The game throws the whole block away instead of "
            "merging it. Fix: copy the vanilla file to the same path and "
            "edit the block there.",
    "W101": "This change silently alters which techs some countries start "
            "with, across the whole world. Double-check the "
            "starting_technology_level chain before shipping.",
    "W102": "This file completely replaces a vanilla file. After every "
            "game patch it silently undoes whatever Paradox changed in "
            "that file. Not a bug - a reminder to re-compare it after "
            "each patch.",
    "P001": "The checker could not fully read this part of the file, so "
            "findings after this point may be missing. Usually caused by "
            "unbalanced brackets or quotes.",
}


def detect_mods() -> list[tuple[str, Path]]:
    """Mods in the Paradox mod folder, newest first, as (label, path)."""
    out = []
    if MOD_DIR.is_dir():
        for d in sorted(MOD_DIR.iterdir()):
            meta = d / ".metadata/metadata.json"
            if d.is_dir() and meta.is_file():
                try:
                    name = json.loads(meta.read_text(encoding="utf-8")).get(
                        "name", d.name)
                except (OSError, ValueError):
                    name = d.name
                out.append((name, d))
    return out


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("EU5 Mod Checker")
        self.geometry("980x640")
        self.minsize(760, 480)

        self.mods = detect_mods()
        self.vanilla = find_vanilla(None)
        self.findings = []
        self.mod_path: Path | None = None

        top = ttk.Frame(self, padding=10)
        top.pack(fill="x")
        ttk.Label(top, text="Your mod:").pack(side="left")
        self.combo = ttk.Combobox(
            top, width=52, state="readonly",
            values=[label for label, _ in self.mods] or ["(no mods found - use Browse)"])
        if self.mods:
            self.combo.current(0)
        self.combo.pack(side="left", padx=8)
        ttk.Button(top, text="Browse...", command=self.browse).pack(side="left")
        self.check_btn = ttk.Button(top, text="Check mod", command=self.check)
        self.check_btn.pack(side="left", padx=12)

        game = ("Game found: rules that compare against vanilla are on."
                if self.vanilla else
                "EU5 install not found: vanilla-aware rules are skipped.")
        self.status = ttk.Label(self, text=game, padding=(12, 0))
        self.status.pack(fill="x")

        mid = ttk.Frame(self, padding=(10, 8))
        mid.pack(fill="both", expand=True)
        cols = ("kind", "rule", "file", "line", "what")
        self.tree = ttk.Treeview(mid, columns=cols, show="headings")
        for col, text, w, anchor in (
                ("kind", "Type", 80, "w"), ("rule", "Rule", 60, "w"),
                ("file", "File", 300, "w"), ("line", "Line", 50, "e"),
                ("what", "What", 420, "w")):
            self.tree.heading(col, text=text)
            self.tree.column(col, width=w, anchor=anchor, stretch=(col in ("file", "what")))
        vsb = ttk.Scrollbar(mid, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="left", fill="y")
        self.tree.tag_configure("error", foreground="#b40000")
        self.tree.tag_configure("warning", foreground="#a86400")
        self.tree.tag_configure("info", foreground="#666666")
        self.tree.bind("<<TreeviewSelect>>", self.show_detail)

        self.detail = tk.Text(self, height=6, wrap="word", relief="flat",
                              background="#f5f4ef", padx=10, pady=8,
                              state="disabled")
        self.detail.pack(fill="x", padx=10)

        bottom = ttk.Frame(self, padding=10)
        bottom.pack(fill="x")
        self.summary = ttk.Label(bottom, text="Pick a mod and press Check mod.")
        self.summary.pack(side="left")
        self.save_btn = ttk.Button(bottom, text="Save report",
                                   command=self.save, state="disabled")
        self.save_btn.pack(side="right")

    # ---------------------------------------------------------- actions
    def browse(self):
        chosen = filedialog.askdirectory(title="Pick your mod folder")
        if chosen:
            p = Path(chosen)
            self.mods.append((p.name + "  (" + str(p) + ")", p))
            self.combo["values"] = [label for label, _ in self.mods]
            self.combo.current(len(self.mods) - 1)

    def check(self):
        if not self.mods:
            messagebox.showinfo("EU5 Mod Checker",
                                "No mod selected. Use Browse to pick your "
                                "mod folder.")
            return
        self.mod_path = self.mods[self.combo.current()][1]
        self.check_btn.configure(state="disabled")
        self.summary.configure(text="Checking...")
        self.tree.delete(*self.tree.get_children())
        threading.Thread(target=self._run_lint, daemon=True).start()

    def _run_lint(self):
        try:
            findings, skipped = run(self.mod_path, self.vanilla)
        except Exception as exc:  # surface, never crash the window
            self.after(0, lambda: self._done(None, str(exc)))
            return
        findings.sort(key=lambda f: f.sort_key())
        self.after(0, lambda: self._done(findings, None))

    def _done(self, findings, error):
        self.check_btn.configure(state="normal")
        if error:
            self.summary.configure(text="Could not check this folder.")
            messagebox.showerror("EU5 Mod Checker", error)
            return
        self.findings = findings
        counts = {"error": 0, "warning": 0, "info": 0}
        for f in findings:
            counts[f.severity] = counts.get(f.severity, 0) + 1
            try:
                rel = f.path.relative_to(self.mod_path)
            except ValueError:
                rel = f.path
            self.tree.insert("", "end", tags=(f.severity,), values=(
                SEVERITY_LABEL.get(f.severity, f.severity), f.rule,
                str(rel), f.line, f.message.split(". ")[0]))
        if not findings:
            self.summary.configure(
                text="No problems found. Your mod is clean.")
        else:
            self.summary.configure(text=(
                f"{counts['error']} problems, {counts['warning']} warnings, "
                f"{counts['info']} notes. Click a line for what to do."))
        self.save_btn.configure(state="normal" if findings else "disabled")

    def show_detail(self, _event):
        sel = self.tree.selection()
        if not sel:
            return
        idx = self.tree.index(sel[0])
        f = self.findings[idx]
        text = f"{f.rule}: {f.message}\n\n{RULE_HELP.get(f.rule, '')}"
        self.detail.configure(state="normal")
        self.detail.delete("1.0", "end")
        self.detail.insert("1.0", text)
        self.detail.configure(state="disabled")

    def save(self):
        if not self.findings:
            return
        default = f"mod-check-{datetime.now():%Y-%m-%d}.txt"
        target = filedialog.asksaveasfilename(
            defaultextension=".txt", initialfile=default,
            filetypes=[("Text file", "*.txt")])
        if not target:
            return
        lines = [f"EU5 Mod Checker report - {self.mod_path}",
                 f"{datetime.now():%Y-%m-%d %H:%M}", ""]
        for f in self.findings:
            lines.append(f"[{SEVERITY_LABEL.get(f.severity)}] {f.rule} "
                         f"{f.path} line {f.line}")
            lines.append(f"  {f.message}")
            help_text = RULE_HELP.get(f.rule)
            if help_text:
                lines.append(f"  {help_text}")
            lines.append("")
        Path(target).write_text("\n".join(lines), encoding="utf-8")
        self.summary.configure(text=f"Report saved: {target}")


def main():
    App().mainloop()


if __name__ == "__main__":
    main()
