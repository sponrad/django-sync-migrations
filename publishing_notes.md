## Publishing to PyPI

### One-time setup

1. **Create a PyPI account** at [pypi.org](https://pypi.org) and enable 2FA.
2. **Create the project on PyPI** (or it will be created on first publish): go to [pypi.org/manage/account/](https://pypi.org/manage/account/) → “Create a new project”, name it `django-sync-migrations`.
3. **Create an API token** (Account → API tokens): scope it to this project (or “Entire account” for testing). Copy the token; you won’t see it again.

### Manual publish (each release)

From the repo root:

```bash
# Bump version (optional; or edit pyproject.toml by hand)
uv version --bump patch

# Build
uv build

# Upload to PyPI (set token once: export UV_PUBLISH_TOKEN=pypi-...)
uv publish --token $(grep UV_PUBLISH_TOKEN .env 2>/dev/null | cut -d= -f2)
# or: uv publish  # if UV_PUBLISH_TOKEN is already in the environment
```

For **Test PyPI** first: add to `pyproject.toml` under `[tool.uv]` (or use a separate config) an index with `publish-url = "https://test.pypi.org/legacy/"` and run `uv publish --index testpypi`.

### Automated publish (recommended): Trusted Publisher

No tokens: push a tag and the workflow publishes to PyPI.

1. **GitHub:** Create an environment named `pypi` (Settings → Environments).
2. **PyPI:** Project → “Publishing” → “Add a new trusted publisher” → GitHub. Set:
   - **Owner/repository:** `sponrad/django-sync-migrations`
   - **Workflow name:** `publish.yml`
   - **Environment name:** `pypi`
3. **Release:** Tag and push. The workflow in `.github/workflows/publish.yml` runs on tags `v*` (e.g. `v0.1.0`).

```bash
git tag -a v0.1.0 -m "Release 0.1.0"
git push --tags
```

[PyPI: Trusted publishers](https://docs.pypi.org/trusted-publishers/).
