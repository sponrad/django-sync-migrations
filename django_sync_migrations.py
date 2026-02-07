#!/usr/bin/env python
"""
Sync Django migrations to match the dev branch, then checkout dev.

Use when on a feature branch with migrations you want to discard before
switching back to dev. Rolls back the database to the migration state on dev,
then checks out the dev branch.

Usage (from your Django project directory; run from PyPI or GitHub):
    uvx django-sync-migrations
    uvx django-sync-migrations --dry-run
    uvx django-sync-migrations --branch develop
    uvx django-sync-migrations --skip-checkout

From GitHub without PyPI:
    uvx --from git+https://github.com/sponrad/django-sync-migrations django-sync-migrations

Requires Django and a reachable database for the migrate step. When run via uvx,
manage.py is executed with your project's .venv Python if present, otherwise
the current interpreter.
"""

import argparse
import importlib
import os
import re
import subprocess
import sys
from pathlib import Path


def git_cmd(args: list[str], cwd: Path = None) -> str | None:
    """Run git command and return stdout, or None on error."""
    try:
        result = subprocess.run(
            ["git"] + args,
            capture_output=True,
            text=True,
            check=True,
            cwd=cwd,
        )
        return result.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def find_project_root() -> Path | None:
    """Walk up from cwd to find directory containing manage.py."""
    for parent in [Path.cwd().resolve(), *Path.cwd().resolve().parents]:
        if (parent / "manage.py").exists():
            return parent
    return None


def get_manage_py_python(project_root: Path) -> str:
    """
    Return the Python executable to use for running manage.py.
    Prefer the project's .venv so that Django and project deps are available
    when this tool is run via uvx (which uses an isolated env without Django).
    """
    venv_python = project_root / ".venv" / "bin" / "python"
    if venv_python.exists():
        return str(venv_python)
    # Windows
    venv_python_win = project_root / ".venv" / "Scripts" / "python.exe"
    if venv_python_win.exists():
        return str(venv_python_win)
    return sys.executable


def get_installed_app_labels(project_root: Path) -> frozenset[str] | None:
    """
    Load Django settings and extract app labels from INSTALLED_APPS.
    Returns None if settings can't be loaded.
    """
    manage_py = project_root / "manage.py"
    if not manage_py.exists():
        return None

    # Resolve DJANGO_SETTINGS_MODULE from manage.py
    content = manage_py.read_text()
    match = re.search(
        r"setdefault\s*\(\s*['\"]DJANGO_SETTINGS_MODULE['\"]\s*,\s*['\"]([^'\"]+)['\"]",
        content,
    )
    if not match:
        return None

    settings_module_name = match.group(1)
    project_root_str = str(project_root.resolve())
    if project_root_str not in sys.path:
        sys.path.insert(0, project_root_str)

    try:
        settings_module = importlib.import_module(settings_module_name)
    except Exception:
        return None

    labels = set()
    for app in getattr(settings_module, "INSTALLED_APPS", []):
        if isinstance(app, str):
            app_path = app
        else:
            app_path = getattr(app, "label", None) or getattr(app, "name", "")
            if not app_path:
                continue
        labels.add(app_path)
        labels.add(app_path.replace(".", "/"))
        parts = app_path.split(".")
        if parts:
            labels.add(parts[0])
            labels.add(parts[-1])
    return frozenset(labels) if labels else None


def get_migration_targets(
    branch: str, repo_root: Path, allowed_labels: frozenset[str] | None
) -> list[tuple[str, str]]:
    """
    Find latest migration for each app on the target branch.
    Returns [(app_label, migration_name), ...] sorted by app_label.
    """
    output = git_cmd(["ls-tree", "-r", branch, "--name-only"], cwd=repo_root)
    if not output:
        return []

    # Group migrations by app: {app_dir: [(number, full_name), ...]}
    app_migrations = {}
    pattern = re.compile(r"^(.+)/migrations/(\d+)_(.+\.py)$")

    for line in output.splitlines():
        if "/.venv/" in line or "/site-packages/" in line:
            continue

        if match := pattern.match(line.strip()):
            app_dir, num_str, name_part = match.groups()

            # Filter by allowed labels if specified
            if allowed_labels and app_dir not in allowed_labels:
                continue

            migration_name = f"{num_str}_{name_part[:-3]}"  # Remove .py
            app_migrations.setdefault(app_dir, []).append((int(num_str), migration_name))

    # Return the latest migration for each app
    return [
        (app, max(migrations, key=lambda x: x[0])[1])
        for app, migrations in sorted(app_migrations.items())
    ]


def run_migrate(
    project_root: Path, app: str, migration: str, dry_run: bool
) -> bool:
    """Run django migration command."""
    python_exe = get_manage_py_python(project_root)
    cmd = [
        python_exe,
        str(project_root / "manage.py"),
        "migrate",
        app,
        migration,
        "--noinput",
    ]

    if dry_run:
        print(f"  [dry-run] would run: {' '.join(cmd)}")
        return True

    try:
        subprocess.run(cmd, cwd=project_root, check=True)
        return True
    except subprocess.CalledProcessError as e:
        print(f"  ERROR: migrate failed: {e}", file=sys.stderr)
        return False


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Reset migrations to dev branch state, then checkout dev.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--branch",
        "-b",
        default=os.environ.get("DEV_BRANCH", "dev"),
        help="Target branch (default: dev or DEV_BRANCH env)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be done without executing",
    )
    parser.add_argument(
        "--skip-checkout",
        action="store_true",
        help="Only reset migrations, do not checkout branch",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Run migration reset even when already on target branch",
    )
    args = parser.parse_args()

    # Validate environment
    project_root = find_project_root()
    if not project_root:
        print(
            "ERROR: Could not find manage.py. Run from project root or subdirectory.",
            file=sys.stderr,
        )
        return 1

    repo_root = Path(git_cmd(["rev-parse", "--show-toplevel"], cwd=project_root) or "")
    if not repo_root or not repo_root.exists():
        print("ERROR: Not a git repository.", file=sys.stderr)
        return 1

    if not git_cmd(["rev-parse", "--verify", args.branch]):
        print(f"ERROR: Branch '{args.branch}' does not exist.", file=sys.stderr)
        return 1

    current_branch = git_cmd(["rev-parse", "--abbrev-ref", "HEAD"])
    if current_branch == args.branch and not args.force:
        print(
            f"Already on {args.branch}. Nothing to do. Use --force to reset anyway."
        )
        return 0

    # Display context
    print(f"Project root: {project_root}")
    print(f"Current branch: {current_branch}")
    print(f"Target branch: {args.branch}")
    if args.dry_run:
        print("(dry run - no changes will be made)")
    print()

    # Find migrations to reset
    allowed_labels = get_installed_app_labels(project_root)
    if not allowed_labels:
        print("WARNING: Could not parse INSTALLED_APPS. Including all repo apps.")

    targets = get_migration_targets(args.branch, repo_root, allowed_labels)

    if not targets:
        print(f"No migrations found on {args.branch}. Nothing to reset.")
    else:
        print(f"Resetting migrations to match {args.branch}:")
        for app, migration in targets:
            print(f"  {app} -> {migration}")
        print()

        for app, migration in targets:
            if not run_migrate(project_root, app, migration, args.dry_run):
                return 1

    # Checkout target branch
    if args.skip_checkout:
        print("Skipping checkout (--skip-checkout).")
    elif args.dry_run:
        print(f"\nWould run: git checkout {args.branch}")
    else:
        print(f"\nChecking out {args.branch}...")
        try:
            subprocess.run(
                ["git", "checkout", args.branch], check=True, cwd=repo_root
            )
            print("Done.")
        except subprocess.CalledProcessError as e:
            print(f"ERROR: git checkout failed: {e}", file=sys.stderr)
            return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
