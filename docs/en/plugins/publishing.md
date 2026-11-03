[简体中文](../../plugins/publishing.md) | **English** | [日本語](../../ja/plugins/publishing.md)

# Packaging, Publishing, and Marketplace

Plugins are distributed as `.xbplugin` ZIP archives. The marketplace is only a JSON index from which the host downloads GitHub release assets. It currently provides no signatures, hashes, compatibility resolution, dependency resolution, version comparison, automatic upgrades, or post-enable rollback.

## Build the Package

```powershell
npm install
npm run pack
```

The scaffold runs type checking -> frontend build -> manifest build -> validation -> ZIP. Direct `xb-plugin pack . .\release\my-plugin-1.0.0.xbplugin` does not run Vite, `tsx`, or type checks first.

The archive must contain `xb-svcb-plugin.json` and every referenced runtime file, such as `dist/frontend/index.html`, `plugin.py`, and optional `vendor/` dependencies. Source, tests, and README are not required at runtime but are included unless ignored.

Automatically ignored: `node_modules/`, `.git/`, `.venv/`, `__pycache__/`, `.pytest_cache/`, and `*.xbplugin`. Tests, `.env`, source maps, lockfiles, screenshots, `vendor/`, and custom caches are not ignored. There is no `.xbpluginignore`; inspect the archive for secrets, private audio, logs, and stale packages.

## Host Limits

| Object | Limit |
| --- | --- |
| Compressed `.xbplugin` | 20 MB |
| Declared extracted size | 50 MB |
| Manifest | 512 KB |
| Entry HTML | 2 MB |
| One `assetData()` / `assetUrl()` resource | 10 MB |
| Python worker call | 30 seconds |
| Page request | 30 seconds by default |

The SDK does not enforce every size before packaging. Large UI libraries count toward the 2 MB single-file HTML limit. Store images/audio as package resources and load them through `assetUrl()`, but do not package models, datasets, or large audio.

## Manifest and Python Dependencies

Run `npm run validate` and confirm stable `id`, incremented `version`, correct runtime, minimal permissions, built frontend entry, relative Python entry, valid page action IDs, and matching Python handlers. The host displays version as a string and does not implement SemVer comparison.

The Python 3.12 host guarantees only the standard library and `xb_svcb_plugin`. Pin other dependencies in `requirements.txt`; `npm run pack` vendors them. The host never runs online `pip install`. Audit transitive licenses, do not copy a complete `.venv`, and remain under package limits.

## GitHub Release

Use a public repository, preferably `xb-svcb-plugin-<name>`, with README, license, source, tests, and build configuration. Document screenshots, ID/version/runtime, manually tested XB-SVCB versions, reasons for each permission, current-user Python execution, network/files/process behavior, settings/data, dependencies and licenses, installation/update/removal, deletion of `plugin-data/<id>` on uninstall, and known limitations.

Release sequence:

1. Update version, install clean dependencies, validate, and run tests.
2. Package and install the final archive in a real host.
3. Create a matching tag and GitHub Release and upload a versioned `.xbplugin` asset.
4. Download that asset from the release page and install it again.
5. Update `market.json`. Do not silently replace an asset at the same URL; retain old releases for manual rollback.

## Marketplace Index

```json
{
  "plugins": [{
    "id": "com.example.hybrid-cover",
    "name": "Hybrid Cover Assistant",
    "version": "1.0.0",
    "description": "Vue collects parameters and Python creates a task.",
    "author": "Your Name",
    "bundle_url": "https://github.com/OWNER/REPO/releases/download/v1.0.0/hybrid-cover-1.0.0.xbplugin"
  }]
}
```

`id` and `bundle_url` are required. Invalid IDs or URLs skip the record. Other fields are display-only; unknown fields are ignored. The downloaded manifest is authoritative and is not cross-checked against index ID/name/version.

Use a public raw URL such as `https://raw.githubusercontent.com/OWNER/REPO/main/market.json`. Initial and redirected URLs must be HTTPS on `github.com`, `api.github.com`, subdomains of `github.com`, `githubusercontent.com`, or its subdomains. Index timeout is 20 seconds and bundle timeout 30 seconds. The host sends no GitHub credentials, so private repositories are unsupported.

## Missing Marketplace Capabilities

- No GPG, Sigstore, attestation, or publisher identity verification.
- No recognized `sha256` field. Release checksums are manual only.
- No `min_app_version`, `max_app_version`, SDK/schema negotiation, or install blocking.
- No version comparison, update badge, background download, or automatic upgrade.
- No npm, Python, system-tool, or inter-plugin dependency installation.
- Code is restored if replacement fails during file/entry validation, but errors found only after enablement require a new release.

Installing the same ID replaces code, disables the plugin, preserves `plugin-data/<id>`, performs no version comparison, and runs no automatic data migration. Implement idempotent migrations in `on_enable`, store completion in `ctx.config`, and back up data before destructive schema changes. Uninstall removes both code and plugin data.

## Security and Release Gate

Python runs with current-user permissions. Declare only real permissions, explain them, avoid unrelated files and credentials, never silently download executables, keep secrets out of source/bundles/indexes, describe transmitted user data, validate external-process arguments, audit `vendor/`, and publish source.

Before release, verify clean builds/tests, browser and host UI, Python success/error paths, fresh install and same-ID replacement, one manifest, present entries, no caches/secrets, all size limits, third-party licenses, matching tag/release/manifest/index versions, installable release URL, and explicit documentation of the missing security/update capabilities. See [Testing](testing.md).
