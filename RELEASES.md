# ADM Release Flow

## What CI builds
- `windows-latest`: `Apex-Download-Manager-windows-x64.exe` and `.zip`
- `macos-latest`: `Apex-Download-Manager-macos-<version>.dmg` and `.pkg`
- `ubuntu-latest`: `Apex-Download-Manager-linux-amd64-<version>.deb` and `.tar.gz`

## Triggers
- Push to `main`: build-only artifacts in GitHub Actions.
- Tag `v*` (example `v1.0.0`): build + draft GitHub Release with attached assets.
- Manual: `workflow_dispatch`.

## Create a release
```bash
git tag v1.0.0
git push origin v1.0.0
```

The workflow creates a draft release so you can review notes and assets before publishing.
