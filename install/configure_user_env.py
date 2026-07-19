"""Persist installer environment values without invoking reg.exe or parsing cmd output."""

from __future__ import annotations

import argparse
import ctypes
import ntpath
import os
import sys
from pathlib import Path
from typing import Iterable


def _path_key(value: str) -> str:
    expanded = os.path.expandvars(value.strip().strip('"'))
    return ntpath.normcase(ntpath.normpath(expanded))


def merge_user_path(
    current: str, candidates: Iterable[str]
) -> tuple[str, list[str], list[str]]:
    known = {
        _path_key(entry)
        for entry in current.split(";")
        if entry.strip()
    }
    added: list[str] = []
    existing: list[str] = []
    for raw_value in candidates:
        value = raw_value.strip().strip('"')
        if not value:
            continue
        key = _path_key(value)
        if key in known:
            existing.append(value)
            continue
        known.add(key)
        added.append(value)

    if not added:
        return current, added, existing
    separator = "" if not current or current.endswith(";") else ";"
    return current + separator + ";".join(added), added, existing


def _parse_env_assignments(specs: Iterable[str]) -> dict[str, str]:
    values: dict[str, str] = {}
    for spec in specs:
        target, separator, source = spec.partition("=")
        if not separator or not target or not source:
            raise ValueError(f"invalid environment mapping: {spec}")
        value = os.environ.get(source, "").strip()
        if value:
            values[target] = value
    return values


def _broadcast_environment_change() -> None:
    result = ctypes.c_size_t()
    ctypes.windll.user32.SendMessageTimeoutW(
        0xFFFF,
        0x001A,
        0,
        "Environment",
        0x0002,
        2000,
        ctypes.byref(result),
    )


def configure_user_environment(
    path_values: Iterable[str],
    string_values: dict[str, str],
    expand_values: dict[str, str],
    *,
    dry_run: bool = False,
) -> None:
    if os.name != "nt":
        raise RuntimeError("user environment configuration is supported only on Windows")

    import winreg

    usable_paths = [value for value in path_values if Path(value).is_dir()]
    changed = False
    with winreg.CreateKeyEx(
        winreg.HKEY_CURRENT_USER,
        "Environment",
        0,
        winreg.KEY_QUERY_VALUE | winreg.KEY_SET_VALUE,
    ) as key:
        try:
            current_path, _ = winreg.QueryValueEx(key, "Path")
            if not isinstance(current_path, str):
                current_path = ""
        except FileNotFoundError:
            current_path = ""

        merged_path, added, existing = merge_user_path(current_path, usable_paths)
        for value in existing:
            print(f"[env] PATH already contains {value}")
        for value in added:
            print(f"[env] PATH += {value}")
        if merged_path != current_path:
            changed = True
            if not dry_run:
                winreg.SetValueEx(key, "Path", 0, winreg.REG_EXPAND_SZ, merged_path)

        for name, value in string_values.items():
            print(f"[env] {name} = {value}")
            changed = True
            if not dry_run:
                winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)
        for name, value in expand_values.items():
            print(f"[env] {name} = {value}")
            changed = True
            if not dry_run:
                winreg.SetValueEx(key, name, 0, winreg.REG_EXPAND_SZ, value)

    if changed and not dry_run:
        _broadcast_environment_change()
    if dry_run:
        print("[env] dry run complete; registry was not changed")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--path-env", action="append", default=[])
    parser.add_argument("--value-env", action="append", default=[])
    parser.add_argument("--expand-value-env", action="append", default=[])
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    try:
        path_values = [os.environ.get(name, "") for name in args.path_env]
        configure_user_environment(
            path_values,
            _parse_env_assignments(args.value_env),
            _parse_env_assignments(args.expand_value_env),
            dry_run=args.dry_run,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"[env] failed to configure user environment: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
