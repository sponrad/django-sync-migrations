# django-sync-migrations

Sync Django migrations to match the dev branch, then checkout dev. Use when on a feature branch with migrations you want to discard before switching back to dev.

## Install / run (from your Django project directory)

**If published on PyPI:**

```bash
uvx django-sync-migrations
uvx django-sync-migrations --dry-run
uvx django-sync-migrations --branch develop
uvx django-sync-migrations --skip-checkout
```

Requires a Django project (with `manage.py`), git, and a reachable database. The tool runs `manage.py migrate` using your project’s `.venv` Python when present.
