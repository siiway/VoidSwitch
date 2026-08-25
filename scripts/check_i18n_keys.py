#!/usr/bin/env python3
"""Check that every i18n key used in the frontend source exists in the locales.

Scans ``frontend/src/**`` for ``t("...")`` / ``t("..." as TK)`` calls and reports
keys that are missing from ``locales/en.ts`` and/or ``locales/zh.ts``. Used as a
pre-commit hook to keep the typed ``Translations`` structure and the live i18n
keys in sync (a missing key renders the raw key string in the UI).

Exit code 0 = all keys present; 1 = missing keys found (with the offending
files printed). Pass ``--fix`` to append missing keys to both locales as
``"key": "<key>",`` placeholders (no-op otherwise).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "frontend" / "src"
LOCALES = [ROOT / "frontend" / "src" / "i18n" / "locales" / "en.ts",
           ROOT / "frontend" / "src" / "i18n" / "locales" / "zh.ts"]

# t("...") and t("..." as TK) call sites.
_CALL_RE = re.compile(r'\bt\(\s*"([^"]+)"(?:\s+as\s+TK)?\s*\)')

# "sec.key": "value" lines inside a section block.
_KEYLINE_RE = re.compile(r'^    ([a-zA-Z0-9_]+):', re.M)


def _defined_keys(text: str) -> set[str]:
    """All defined ``section.key`` keys, derived from the TS object structure."""
    defined: set[str] = set()
    section: str | None = None
    for line in text.splitlines():
        m = re.match(r'^  ([a-zA-Z0-9_]+): \{', line)
        if m:
            section = m.group(1)
            continue
        if line.rstrip().endswith("},") or line.rstrip() == "},":
            pass
        if section:
            m2 = re.match(r'^    ([a-zA-Z0-9_]+):', line)
            if m2:
                defined.add(f"{section}.{m2.group(1)}")
    return defined


def _used_keys() -> dict[str, set[str]]:
    """Source file -> set of keys it references via t(\"…\")."""
    used: dict[str, set[str]] = {}
    for path in SRC.rglob("*.ts*"):
        if "locales" in path.parts or path.name in {"vite-env.d.ts", "main.tsx"}:
            continue
        try:
            text = path.read_text()
        except OSError:
            continue
        keys = set(_CALL_RE.findall(text))
        if keys:
            used[str(path.relative_to(ROOT))] = keys
    return used


def _locales():
    data = {}
    for path in LOCALES:
        data[path.name] = _defined_keys(path.read_text())
    return data


def main() -> int:
    fix = "--fix" in sys.argv
    locales = _locales()
    used = _used_keys()

    missing: list[tuple[str, str, set[str]]] = []
    for rel, keys in sorted(used.items()):
        for key in sorted(keys):
            for name, defined in locales.items():
                if key not in defined:
                    missing.append((rel, name, {key}))

    if not missing:
        print("i18n keys: all referenced keys present in en.ts and zh.ts")
        return 0

    if fix:
        # Group by locale and append missing keys as placeholders before the
        # section's closing brace (best-effort; operators fill in real text).
        by_locale: dict[str, set[str]] = {}
        for _rel, name, keys in missing:
            by_locale.setdefault(name, set()).update(keys)
        for name, keys in by_locale.items():
            path = next(p for p in LOCALES if p.name == name)
            text = path.read_text()
            # Simple approach: append a placeholder block to the matching
            # section if it exists, else leave a comment. Keep it conservative.
            appended = []
            for key in sorted(keys):
                if key in _defined_keys(text):
                    continue
                # find the section and its last line to insert before the close
                sec, _, sub = key.partition(".")
                marker = f"  {sec}: {{"
                if marker not in text:
                    continue
                idx = text.find(marker)
                close = text.find("\n  },", idx)
                if close == -1:
                    continue
                insertion = f'    {sub}: "{key}",\n'
                if insertion not in text:
                    text = text[:close] + "\n" + insertion + text[close:]
                    appended.append(key)
            if appended:
                path.write_text(text)
                print(f"[fix] {name}: added {len(appended)} placeholder key(s)")
        # Re-check to report what could not be auto-fixed.
        locales = _locales()
        still_missing = [
            (rel, name, {k}) for rel, keys in used.items() for k in keys
            for name, defined in locales.items() if k not in defined
        ]
        if still_missing:
            for rel, name, keys in still_missing:
                for k in keys:
                    print(f"[fix] unresolved: {rel}: {name} missing {k}")
            return 1
        return 0

    for rel, name, keys in missing:
        for k in keys:
            print(f"{rel}: missing {name} key '{k}'")
    print("\nAdd the keys to frontend/src/i18n/locales/en.ts and zh.ts "
          "(or run with --fix to insert placeholders).")
    return 1


if __name__ == "__main__":
    sys.exit(main())
