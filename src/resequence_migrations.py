"""
Check for migrations that would require a merge and resequence them.

When on a feature branch rebased onto dev, migrations brought in from dev can
leave your feature migrations with conflicting or "behind" numbering. This
detects migrations that exist only on the current branch (not on dev),
deletes them, and runs makemigrations so new migrations get numbers that
follow dev.
"""

import subprocess
import sys
from pathlib import Path

from .django_sync_migrations import (
    get_all_migration_files_on_branch,
    get_installed_app_dirs,
    get_manage_py_python,
    get_migration_files_in_working_tree,
)


def check_for_potential_merge_migrations(
    branch: str,
    project_root: Path,
    repo_root: Path,
    allowed_labels: frozenset[str] | None,
) -> dict[str, set[str]]:
    """
    Find migrations that exist in the working tree but not on the target branch.
    These are "feature-only" migrations that may need to be resequenced.

    Returns {app_label: set of migration filenames to remove}, only including
    apps where we have at least one feature-only migration and the branch has
    migrations for that app (so we're "behind" and need to resequence).
    """
    on_branch = get_all_migration_files_on_branch(branch, repo_root, allowed_labels)
    in_tree = get_migration_files_in_working_tree(project_root, allowed_labels)

    to_remove: dict[str, set[str]] = {}
    for app, tree_files in in_tree.items():
        branch_files = on_branch.get(app, set())
        feature_only = tree_files - branch_files
        if not feature_only:
            continue
        # Only resequence if dev has migrations for this app (so numbering matters)
        if branch_files:
            to_remove[app] = feature_only

    return to_remove


def delete_migration_files(
    project_root: Path, to_remove: dict[str, set[str]]
) -> list[Path]:
    """Delete the given migration files. Returns list of deleted paths."""
    deleted: list[Path] = []
    for app, filenames in to_remove.items():
        mig_dir = project_root / app / "migrations"
        if not mig_dir.is_dir():
            continue
        for name in filenames:
            path = mig_dir / name
            if path.exists():
                path.unlink()
                deleted.append(path)
    return deleted


def run_makemigrations(project_root: Path, dry_run: bool) -> bool:
    """Run django makemigrations. Returns True on success."""
    python_exe = get_manage_py_python(project_root)
    cmd = [python_exe, str(project_root / "manage.py"), "makemigrations"]

    if dry_run:
        print(f"  [dry-run] would run: {' '.join(cmd)}")
        return True

    try:
        subprocess.run(cmd, cwd=project_root, check=True)
        return True
    except subprocess.CalledProcessError as e:
        print(f"  ERROR: makemigrations failed: {e}", file=sys.stderr)
        return False


def run_resequence(
    branch: str,
    project_root: Path,
    repo_root: Path,
    *,
    dry_run: bool = True,
    yes: bool = False,
    verbose: bool = False,
) -> int:
    """
    Detect feature-only migrations (not on branch), optionally delete them
    and run makemigrations. Default is dry-run; use dry_run=False and yes=True
    to apply without prompt.
    """
    allowed_labels = get_installed_app_dirs(project_root, verbose=verbose)
    if not allowed_labels:
        print("WARNING: Could not load INSTALLED_APPS. Including all repo apps.")

    to_remove = check_for_potential_merge_migrations(
        branch, project_root, repo_root, allowed_labels
    )

    if not to_remove:
        print("No feature-only migrations found. Nothing to resequence.")
        return 0

    total = sum(len(files) for files in to_remove.values())
    print(f"Found {total} migration(s) on this branch that are not on '{branch}':")
    for app in sorted(to_remove.keys()):
        for f in sorted(to_remove[app]):
            print(f"  {app}/migrations/{f}")
    print()

    if dry_run:
        print("(dry run - no files will be deleted)")
        print("Would delete the above files, then run: python manage.py makemigrations")
        print("To apply, run with --apply and confirm when prompted (or --yes).")
        return 0

    if not yes:
        try:
            reply = input("Delete these migrations and run makemigrations? [y/N]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\nAborted.")
            return 1
        if reply not in ("y", "yes"):
            print("Aborted.")
            return 1

    deleted = delete_migration_files(project_root, to_remove)
    print(f"Deleted {len(deleted)} file(s).")
    if not run_makemigrations(project_root, dry_run=False):
        return 1
    print("Done. Review the new migration(s) and commit as needed.")
    return 0
