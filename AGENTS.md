# VoidSwitch

## Lint & Typecheck

```bash
# Backend
ruff check backend/
ty check

# Frontend
cd frontend && npm run lint
```

All `ty check` unresolved-import diagnostics are pre-existing (no venv at system level) — only new type errors from changed code should be fixed.
