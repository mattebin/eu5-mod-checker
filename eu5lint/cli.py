"""Command line interface for eu5lint."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .engine import all_rules, run

DEFAULT_STEAM_PATHS = (
    r"C:\Program Files (x86)\Steam\steamapps\common\Europa Universalis V",
    r"C:\SteamLibrary\Steam\steamapps\common\Europa Universalis V",
    r"C:\SteamLibrary\steamapps\common\Europa Universalis V",
    r"D:\SteamLibrary\steamapps\common\Europa Universalis V",
)


def find_vanilla(explicit: str | None) -> Path | None:
    if explicit:
        path = Path(explicit)
        return path if path.is_dir() else None
    env = os.environ.get("EU5_PATH")
    if env and Path(env).is_dir():
        return Path(env)
    for candidate in DEFAULT_STEAM_PATHS:
        if Path(candidate).is_dir():
            return Path(candidate)
    return None


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="eu5lint",
        description=(
            "Checks an EU5 mod for silent engine traps: mistakes the game "
            "loads without complaining about and simply ignores."))
    parser.add_argument("mod", help="path to the mod folder")
    parser.add_argument(
        "--vanilla",
        help=(
            "path to the EU5 install (the folder that contains 'game'). "
            "Auto-detected from common Steam locations or the EU5_PATH "
            "environment variable when omitted. Enables the vanilla-aware "
            "rules."))
    parser.add_argument(
        "--no-vanilla", action="store_true",
        help="skip vanilla auto-detection and run only self-contained rules")
    parser.add_argument(
        "--game-version",
        help=(
            "your game version, for example 1.3.11. Auto-detected from "
            "continue_game.json when omitted. Used to warn when the game "
            "is newer than the version the rules were verified on."))
    parser.add_argument(
        "--fix", action="store_true",
        help=(
            "apply the automatic fixes for findings that can be repaired "
            "mechanically with confidence (BOM, split loc strings, "
            "do-nothing identical overrides, tick compensation values), "
            "then re-run the check"))
    parser.add_argument(
        "--format", choices=("text", "json"), default="text")
    parser.add_argument(
        "--rules", help="comma-separated rule ids to run (default: all)")
    parser.add_argument(
        "--disable", help="comma-separated rule ids to skip")
    parser.add_argument(
        "--strict", action="store_true",
        help="exit with code 1 on warnings too, not only errors")
    parser.add_argument(
        "--list-rules", action="store_true", help="list rules and exit")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    from . import rules as _rules  # noqa: F401  (register rules)

    if args.list_rules:
        for rule_id, description, needs_vanilla, _fn in all_rules():
            tag = " (needs --vanilla)" if needs_vanilla else ""
            print(f"{rule_id}  {description}{tag}")
        return 0

    mod_path = Path(args.mod)
    if not mod_path.is_dir():
        print(f"error: mod path not found: {mod_path}", file=sys.stderr)
        return 2

    vanilla = None if args.no_vanilla else find_vanilla(args.vanilla)
    if args.vanilla and vanilla is None:
        print(f"error: vanilla path not found: {args.vanilla}",
              file=sys.stderr)
        return 2

    enabled = set(args.rules.split(",")) if args.rules else None
    disabled = set(args.disable.split(",")) if args.disable else None

    from .gameversion import (VERIFIED_GAME_VERSION, detect_game_version,
                              version_notice)
    detected_version = args.game_version or detect_game_version()
    notice, _is_warning = version_notice(detected_version)

    findings, skipped = run(mod_path, vanilla, enabled, disabled)

    if args.fix:
        from .fixes import apply_fixes
        applied = apply_fixes(findings, mod_path)
        for line in applied:
            print(f"FIXED   {line}")
        if applied:
            print()
            findings, skipped = run(mod_path, vanilla, enabled, disabled)

    errors = sum(1 for f in findings if f.severity == "error")
    warnings = sum(1 for f in findings if f.severity == "warning")
    infos = sum(1 for f in findings if f.severity == "info")

    if args.format == "json":
        payload = {
            "mod": str(mod_path),
            "vanilla": str(vanilla) if vanilla else None,
            "rules_verified_on": VERIFIED_GAME_VERSION,
            "detected_game_version": detected_version,
            "skipped_rules": skipped,
            "summary": {"errors": errors, "warnings": warnings,
                        "infos": infos},
            "findings": [
                {"rule": f.rule, "severity": f.severity,
                 "path": str(f.path), "line": f.line, "message": f.message}
                for f in findings],
        }
        print(json.dumps(payload, indent=2))
    else:
        if vanilla:
            print(f"vanilla: {vanilla}")
        else:
            print("vanilla: not found (vanilla-aware rules skipped, "
                  "pass --vanilla to enable)")
        print(notice)
        for f in findings:
            try:
                shown = f.path.relative_to(mod_path)
            except ValueError:
                shown = f.path
            print(f"{f.severity.upper():7} {f.rule} {shown}:{f.line}")
            print(f"        {f.message}")
        if skipped:
            print(f"skipped (need vanilla): {', '.join(skipped)}")
        print(f"\n{errors} errors, {warnings} warnings, {infos} notes")

    if errors:
        return 1
    if args.strict and warnings:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
