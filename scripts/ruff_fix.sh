#!/usr/bin/env bash
# prek hook helper: run a backend fixer, then re-stage the files it changed.
#
# Usage: scripts/ruff_fix.sh <tool> -- <files...>
#   tool = check|format
#
# Runs `uv run --project backend ruff <tool>` on the given files, then `git add`s
# them so the autofix is committed as part of the change. Without the re-stage,
# prek would report "files were modified by this hook" and fail the commit.
set -euo pipefail

tool="${1:?usage: ruff_fix.sh check|format -- <files>}"
shift
if [ "${1:-}" = "--" ]; then
    shift
fi

if [ "$tool" = "format" ]; then
    uv run --project backend ruff format "$@"
else
    uv run --project backend ruff check --fix "$@"
fi

# Stage whatever the fixer touched so the commit includes the autofixes.
git add -- "$@"
