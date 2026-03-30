# Railway + Railpack + Poetry Build Configuration

**Status:** Working as of 2026-03-31 (build time ~69s)  
**Relevant commit chain:** `ac3b190` → `636b0a0` → `aee218f`

---

## Context

This is a monorepo with `backend/` and `frontend/` services deployed separately on Railway. The backend is a FastAPI + Poetry Python project. Getting Railpack (Railway's build system) to correctly run `poetry install` took several debugging cycles — this doc captures the exact solution and the reasoning behind each piece.

---

## Final Working Configuration

**`backend/railpack.json`**
```json
{
  "$schema": "https://schema.railpack.com",
  "steps": {
    "install": {
      "commands": [
        { "src": "pyproject.toml", "dest": "pyproject.toml" },
        { "src": "poetry.lock", "dest": "poetry.lock" },
        "poetry config virtualenvs.in-project true",
        "poetry install --no-interaction --no-ansi --only main --no-root"
      ]
    }
  }
}
```

**`railway.json`** (repo root)
```json
{
  "builder": "RAILPACK"
}
```

The Railway service's **Root Directory** is set to `/backend` in the Railway dashboard.

---

## What Each Piece Does

### `"builder": "RAILPACK"` in `railway.json`
Explicitly forces Railway to use Railpack instead of Nixpacks. Without this, Railway may fall back to Nixpacks (which uses a different build config system and ignored `railpack.json`).

### Root Directory = `/backend`
Scopes the build context to only the `backend/` folder. Railpack receives `backend/` contents as the root — so `pyproject.toml` would be at `/app/pyproject.toml` in the container, not `/app/backend/pyproject.toml`.

### `railpack.json` placed in `backend/`
Railpack looks for `railpack.json` at the root of the build context. Since Root Directory = `/backend`, placing it in `backend/` means it's at the build context root.

---

## Why Each Command in `railpack.json` Is Required

### 1. The copy commands
```json
{ "src": "pyproject.toml", "dest": "pyproject.toml" },
{ "src": "poetry.lock", "dest": "poetry.lock" },
```

**Critical.** Railpack's install step runs in an **isolated Docker build stage**. Files from your repo are not automatically present — they must be explicitly copied in via copy commands in the `commands` array.

When you override a step's `commands` entirely (as we do here), you replace the provider's auto-generated commands, including its auto-generated copy commands. Without these explicit copies, `pyproject.toml` never lands in `/app`, and Poetry fails with:

```
Poetry could not find a pyproject.toml file in /app or its parents
```

The copy commands use Railpack's copy command format: `src` is relative to the build context root (i.e., relative to `backend/`), `dest` is where it lands inside the build container.

### 2. `poetry config virtualenvs.in-project true`
Tells Poetry to create the virtualenv inside the project at `/app/.venv` instead of the default global cache location (`~/.cache/pypoetry/virtualenvs/`). 

This matters because Railpack's deploy stage explicitly copies `/app/.venv` from the build stage into the runtime image. If the venv is elsewhere, it won't be included in the final image and `poetry run` will fail at runtime.

### 3. `poetry install --no-interaction --no-ansi --only main --no-root`

- `--no-interaction` — prevents prompts that would hang the build
- `--no-ansi` — cleaner build logs
- `--only main` — installs only production dependencies, skips dev groups
- **`--no-root`** — **critical.** Without this, Poetry also tries to install the current project itself as a Python package (i.e., build `rapid-reports-ai` from source). The install step only has `pyproject.toml` and `poetry.lock` — the actual source code (`src/`) is not copied in at this stage. Poetry fails silently with exit code 1 trying to build the package.

`--no-root` is the standard pattern for Dockerfile dependency caching layers. The project source is available at runtime via `PYTHONPATH=/app/src` set in the Procfile — so the package doesn't need to be pip-installed.

---

## What Was Deleted

- **`backend/requirements.txt`** — was the original dependency file. Railpack's Python provider detected it and used `pip install -r requirements.txt` instead of Poetry. It didn't include `firecrawl-py`, causing `ModuleNotFoundError` at runtime. Deleting it forced Railpack to detect Poetry via `pyproject.toml`.
- **`backend/nixpacks.toml`** — Nixpacks config. Irrelevant once we switched to Railpack (via `railway.json`). Nixpacks and Railpack are entirely separate systems with different config files.

---

## Debugging Chronology

| Build | Config | Failure | Root Cause |
|-------|--------|---------|------------|
| Pre-fix | `requirements.txt` + Nixpacks | `ModuleNotFoundError: No module named 'firecrawl'` at runtime | `firecrawl-py` not in `requirements.txt`; Nixpacks used pip, not Poetry |
| 1 | `railpack.json` with bare `poetry install` | `Poetry could not find a pyproject.toml file in /app` | Install step runs in isolated filesystem; `pyproject.toml` was never copied in |
| 2 | Added explicit `{ "src": "pyproject.toml", ... }` copy | Exit code 1 after all packages installed | Poetry tried to build+install the project package from source, but `src/` didn't exist in the install step |
| 3 ✓ | Added `--no-root` | **Build succeeded in 69s** | All packages installed; project package install skipped; app runs via `PYTHONPATH` |

---

## Key Railpack Concepts Learned

1. **Step isolation:** Each Railpack step runs in its own Docker build stage with an empty filesystem (minus toolchain). Files must be explicitly brought in via `inputs` layers or copy commands.

2. **Command array replacement:** Specifying `"commands": [...]` in `railpack.json` for an existing provider step **replaces** all provider-generated commands, including file copy commands. Use `"..."` as a list item to instead *extend* the provider's commands (append your commands after the generated ones).

3. **`copy / /app`** in build plan output means Railpack copies the build context root (scoped by Root Directory) into `/app`. This happens in the final app stage, not the install stage.

4. **`virtualenvs.in-project true`** is required for Railpack to correctly copy the venv into the runtime image.

5. **`--no-root`** is required in any split install/build Docker layer where the project source code is not yet present.

---

## Procfile (unchanged, for reference)

```
web: export PYTHONPATH=/app/src:$PYTHONPATH && poetry run python fix_migration_state.py && poetry run uvicorn rapid_reports_ai.main:app --host 0.0.0.0 --port $PORT
```

`PYTHONPATH=/app/src` is what makes the app importable without the project being pip-installed as a package (`--no-root`).
