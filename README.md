# django-sync-migrations

From a feature branch, sync Django migrations to match the dev branch, then checkout dev. Use when on a feature branch with migrations you want to discard before switching back to dev.

A time saver when you are doing a lot of reviews of Django code and find yourself undoing feature branch migrations to match the base branch before you switch back to it.

## Install

**From your Django project**:

```bash
pip install django-sync-migrations
```

Or without installing (requires [uv](https://docs.astral.sh/uv/)):

```bash
uvx django-sync-migrations
```

## Run

From your Django project directory (the one with `manage.py`):

```bash
django-sync-migrations              # reset migrations to dev, then checkout dev
django-sync-migrations --dry-run   # show what would be done
django-sync-migrations --branch develop
django-sync-migrations --skip-checkout   # only reset migrations, don’t checkout
```

Requires a Django project (with `manage.py`), git, and a reachable database. The tool runs `manage.py migrate` using your project’s Python.
