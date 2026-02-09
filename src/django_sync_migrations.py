#!/usr/bin/env python
"""
Sync Django migrations to match the dev branch, then checkout dev.

Use when on a feature branch with migrations you want to discard before
switching back to dev. Rolls back the database to the migration state on dev,
then checks out the dev branch.
"""

import argparse
import importlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path


def git_cmd(args: list[str], cwd: Path | None = None) -> str | None:
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


def get_installed_app_dirs(project_root: Path, verbose: bool = False) -> frozenset[str] | None:
    """
    Get the set of app directory names that are in INSTALLED_APPS.
    Only these apps' migrations are reset; in-repo apps not in INSTALLED_APPS are skipped.
    Uses first segment of each INSTALLED_APPS entry (e.g. "app_name" from "app_name.apps.AppConfig").
    """
    def _log(msg: str) -> None:
        if verbose:
            print(msg)

    manage_py = project_root / "manage.py"
    if not manage_py.exists():
        return None

    def app_paths_from_module(settings_module) -> list[str] | None:
        paths = []
        for app in getattr(settings_module, "INSTALLED_APPS", []):
            if isinstance(app, str):
                paths.append(app)
            else:
                path = getattr(app, "label", None) or getattr(app, "name", "")
                if path:
                    paths.append(path)
        return paths if paths else None

    # Try importing settings (fast, can fail if settings have side effects)
    content = manage_py.read_text()
    match = re.search(
        r"setdefault\s*\(\s*['\"]DJANGO_SETTINGS_MODULE['\"]\s*,\s*['\"]([^'\"]+)['\"]",
        content,
    )
    if match:
        project_root_str = str(project_root.resolve())
        if project_root_str not in sys.path:
            sys.path.insert(0, project_root_str)
        try:
            settings_module = importlib.import_module(match.group(1))
            paths = app_paths_from_module(settings_module)
            if paths:
                _log("INSTALLED_APPS: using direct settings import")
                return frozenset(p.split(".")[0] for p in paths if p)
        except Exception:
            _log("INSTALLED_APPS: direct import failed, trying manage.py shell")

    # Fallback: run Python code directly with Django setup
    python_exe = get_manage_py_python(project_root)

    # Try using manage.py shell
    shell_code = "import json; from django.conf import settings; apps = [x if isinstance(x, str) else (getattr(x, 'label', None) or getattr(x, 'name', str(x))) for x in settings.INSTALLED_APPS]; print(json.dumps(apps))"
    try:
        result = subprocess.run(
            [python_exe, str(manage_py), "shell", "-c", shell_code],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0 and result.stdout.strip():
            try:
                # The shell command may print extra output, so find the JSON array
                stdout = result.stdout.strip()
                # Look for a line starting with '[' - that's our JSON
                for line in stdout.splitlines():
                    line = line.strip()
                    if line.startswith('['):
                        paths = json.loads(line)
                        if paths:
                            _log("INSTALLED_APPS: using manage.py shell")
                            return frozenset(p.split(".")[0] for p in paths if p)
                        break
            except json.JSONDecodeError:
                pass  # Try alternate method below
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    # Alternate method: run Python directly with django.setup()
#     if match:
#         _log("INSTALLED_APPS: shell failed, trying python -c django.setup()")
#         setup_code = f"""
# import sys
# import os
# import json
# os.environ.setdefault('DJANGO_SETTINGS_MODULE', '{match.group(1)}')
# sys.path.insert(0, '{project_root}')
# import django
# django.setup()
# from django.conf import settings
# apps = [x if isinstance(x, str) else (getattr(x, 'label', None) or getattr(x, 'name', str(x))) for x in settings.INSTALLED_APPS]
# print(json.dumps([p for p in apps if p]))
# """
#         try:
#             result = subprocess.run(
#                 [python_exe, "-c", setup_code],
#                 cwd=project_root,
#                 capture_output=True,
#                 text=True,
#                 timeout=30,
#             )
#             if result.returncode == 0 and result.stdout.strip():
#                 paths = json.loads(result.stdout.strip())
#                 if paths:
#                     _log("INSTALLED_APPS: using python -c django.setup()")
#                     return frozenset(p.split(".")[0] for p in paths if p)
#         except (json.JSONDecodeError, subprocess.TimeoutExpired, FileNotFoundError):
#             pass

    return None


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
        "--verbose",
        "-v",
        action="store_true",
        help="Print which method was used to load INSTALLED_APPS (to stdout)",
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
    if current_branch == args.branch:
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

    # Find migrations to reset: only apps in INSTALLED_APPS that have migrations in the repo
    allowed_labels = get_installed_app_dirs(project_root, verbose=args.verbose)
    if not allowed_labels:
        print("WARNING: Could not load INSTALLED_APPS. Including all repo apps.")

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
