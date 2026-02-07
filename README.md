# django-sync-migrations

Sync Django migrations to match the dev branch, then checkout dev. Use when on a feature branch with migrations you want to discard before switching back to dev.

## Install

**From your Django project**:

```bash
pip install django-sync-migrations
```

WIP Or without installing (requires [uv](https://docs.astral.sh/uv/)):

```bash
uvx django-sync-migrations
```

> **Note:** `uvx` install is not working currently (the tool can’t see your project’s Django/settings when run in uv’s isolated env). Trying to figure this out.

## Run

From your Django project directory (the one with `manage.py`):

```bash
django-sync-migrations              # reset migrations to dev, then checkout dev
django-sync-migrations --dry-run   # show what would be done
django-sync-migrations --branch develop
django-sync-migrations --skip-checkout   # only reset migrations, don’t checkout
```

Requires a Django project (with `manage.py`), git, and a reachable database. The tool runs `manage.py migrate` using your project’s Python.
