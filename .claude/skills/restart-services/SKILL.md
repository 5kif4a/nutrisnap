---
name: restart-services
description: Restart NutriSnap docker-compose services (api, bot, postgres, qdrant). Use when the user says "restart bot", "restart api", "перезапусти", "перезапустить сервисы", "compose restart", "rebuild", or when changes were made that won't be picked up by watchfiles auto-reload (dependency changes, env changes, Dockerfile changes, compose changes).
---

# Restart NutriSnap services

In dev, code under `backend/app/**.py` auto-reloads — api via `uvicorn --reload`, bot via `watchfiles`. Use this skill only when auto-reload won't catch the change.

## When auto-reload is NOT enough

Hard restart is required when any of these change:

| Changed | Why auto-reload won't pick it up |
|---|---|
| `backend/pyproject.toml`, `uv.lock` | new dep needs `pip install` inside container — must rebuild image |
| `backend/Dockerfile`, `backend/.dockerignore` | image layers cached — must rebuild |
| `docker-compose.yml` | container config (envs, volumes, healthcheck) — must `up -d` |
| `backend/.env` | env vars injected at container start, not read at runtime |
| `backend/alembic/**` | migration files are mounted but `alembic upgrade head` must be re-run |
| Files outside `backend/app/` (e.g. `backend/scripts/`) | watchfiles only watches `/app/app/` |

If only `*.py` under `backend/app/**` changed — DO NOTHING, watchfiles handles it.

## Commands

Always run from project root (`/Users/alikhan_shorin/Documents/personal/nfactorial llm engineer/final-project/nutrisnap`).

### Soft restart (config / env change, no image rebuild)
```bash
podman compose restart <service>
# e.g.:
podman compose restart bot
podman compose restart api
```

Use this when:
- Changed `.env`
- Changed `docker-compose.yml` healthcheck/command (without rebuild)
- Bot got stuck or process unhealthy

### Rebuild (Dockerfile or deps changed)
```bash
podman compose up -d --build <service>
# or all:
podman compose up -d --build
```

Use this when:
- Added/removed packages in `pyproject.toml`
- Modified `Dockerfile`
- Modified `backend/scripts/healthcheck*.py` (it's copied into image)

### Run migrations after schema change
```bash
podman compose run --rm migrate
```

`migrate` service auto-runs on `up`, but on schema changes during dev you can re-run manually.

### Reset everything (nuke db + volumes)
```bash
podman compose down -v
podman compose up -d --build
```

**Confirm with the user before** running with `-v` — wipes Postgres + Qdrant data.

### Verify health after restart

```bash
podman ps --filter "name=nutrisnap" --format "table {{.Names}}\t{{.Status}}"
```

All four should be `(healthy)`. If anything is `(unhealthy)`:

```bash
podman logs --tail 30 nutrisnap-<service>
```

## Workflow

1. **Look at what changed** (`git status` or recent diffs).
2. **Pick the minimum action** — restart is faster than rebuild.
3. **Run the command**, stream output if it's a build (~30s).
4. **Verify health** with `podman ps`.
5. **Tail logs** for the affected service for 5-10s to make sure no startup errors.
6. **Report** what was restarted and whether it's healthy.

## Don't do

- ❌ Don't restart on every `*.py` save under `backend/app/` — watchfiles already handles it
- ❌ Don't use `down -v` without explicit user confirmation — data loss
- ❌ Don't use `--no-cache` on builds unless image cache is suspected broken
- ❌ Don't run `docker compose` — user has only `podman compose` available
- ❌ Don't pull image versions — pinned tags must match what's in `docker-compose.yml`
