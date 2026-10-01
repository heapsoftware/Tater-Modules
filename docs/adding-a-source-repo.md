# Adding a new source repo to the master index

Self-contained walkthrough: take a new verba/core extension repo from "just a GitHub
repo" to "shows up in Tater's shop for all devices". Read top to bottom once; after that
the checklist at the end is all you need per release.

## The big picture

```
 your source repo (GitHub, public)                THIS REPO (Tater-Master)
 ┌─────────────────────────────────┐              ┌──────────────────────────────────┐
 │ manifest.json  (or              │  fetched     │ repos.json   <- you add one line │
 │ core_manifest.json)  +  .py     │ ──────────>  │ build_manifest.py  (checks A-F)  │
 │ (the .py stays HERE forever)    │   by         │        │                          │
 └─────────────────────────────────┘   id/        │        v                          │
                                                 │ manifest.json  { verbas: [...],   │
   Tater on any device                            │                    cores: [...] } │
 ┌──────────────────────────┐      reads         │        │  pushed to GitHub        │
 │ shop UI  <-  one URL     │ <──────────────────┤        v                          │
 │ (Verbas page + Cores     │  raw URL           │  raw.githubusercontent.com/...    │
 │  page, same URL twice)   │                    └──────────────────────────────────┘
 │ install/update .py files │
 └──────────────────────────┘
```

Rules of the road (what Tater actually does — this is what the steps below are
implementing):

- **One master manifest serves both UIs.** `manifest.json` contains both a `verbas`
  array and a `cores` array. Tater's verba store reads `verbas`, the core store reads
  `cores`; each ignores the other. You paste the same URL into both UIs.
- **`id` is sacred.** The installed file is named `<id>.py` (verbas) or `<id>_core.py`
  (cores). Change an id and Tater treats the item as a brand-new plugin (old file
  stranded, "installed" state lost). Never reuse ids across your repos, never change
  one. Never reuse an official Tater_Shop id either — the official shop is loaded first
  and wins id dedup, so your item would silently vanish from the shop.
- **Version pairing is what makes updates work.** Tater compares the manifest item's
  `version` against the version read from the *installed .py's class attribute*
  (`version`, `__version__`, or `plugin_version` — first non-empty, else 0.0.0). The
  update button appears only when manifest version > installed version. So at every
  release: bump the class attribute **and** the manifest `version` to the *same* value.
  This exact desync shipped in one of your repos (v0.3.0–v0.4.1) and silently killed
  updates — check F of the build exists to catch it.
- **`sha256` is a hard gate.** If present, Tater hashes the downloaded file and *fails
  the install* on any mismatch. The manifest's sha must be the hash of the exact file
  bytes on GitHub.
- **The master never stores .py files.** Each item's `entry` in the master is an
  absolute `raw.githubusercontent.com` URL into the source repo; Tater downloads
  straight from there. (The build script rewrites each source's relative `entry` into
  that URL — keep source entries *relative*.)

## Part 1 — the source repo (on GitHub)

### Requirements

1. Public GitHub repo (or the master repo would need a deploy key — just make it
   public), default branch `main` (or whatever; put the real branch in `repos.json`).
2. The .py plugin file in the repo (e.g. `verba/my_thing.py` or `cores/my_thing_core.py`).
3. A schema-1 manifest at the repo root:
   - verba repo → `manifest.json` with a `verbas` array
   - core repo → `core_manifest.json` with a `cores` array

### Templates (copy, fill in, keep the field order)

**Verba** (`manifest.json`):

```json
{
  "schema": 1,
  "verbas": [
    {
      "id": "my_new_verba",
      "name": "My New Verba",
      "version": "1.0.0",
      "min_tater_version": "99",
      "description": "One or two lines, shown in the shop.",
      "portals": ["webui"],
      "notifier": false,
      "settings_category": "My New Verba",
      "tags": ["example"],
      "entry": "verba/my_new_verba.py",
      "sha256": "<paste sha256sum output here>"
    }
  ]
}
```

**Core** (`core_manifest.json`):

```json
{
  "schema": 1,
  "cores": [
    {
      "id": "my_new_core",
      "name": "My New Core",
      "module_key": "my_new_core",
      "version": "1.0.0",
      "min_tater_version": "1.2.0",
      "description": "One or two lines, shown in the shop.",
      "settings_category": "My New Core Settings",
      "required_settings_count": 3,
      "autostart_key": "my_new_core_running",
      "tags": ["example"],
      "entry": "cores/my_new_core.py",
      "sha256": "<paste sha256sum output here>"
    }
  ]
}
```

### Field reference

| Field | Required | Notes |
|---|---|---|
| `id` | yes | `lowercase_underscore`. **Stable forever** — it's the installed filename. Unique across *all* your repos + the official shop. |
| `name` | yes | Display name in the shop; the master sorts items by it. |
| `version` | yes | `X.Y[.Z]`. **Must equal the .py class attribute** (`version` / `__version__`). Bump both together every release. |
| `entry` | yes | Path to the .py **relative to the repo root** (e.g. `verba/foo.py`). The master rewrites this to an absolute raw URL — keep it relative. |
| `sha256` | yes | 64 hex chars: `sha256sum verba/foo.py` → first column. Must match the file's exact bytes on GitHub. |
| `description` | recommended | Shop listing text. |
| `min_tater_version` | optional | Skip if the extension runs on anything. |
| `portals`, `notifier`, `settings_category`, `tags` | optional (verba) | Copied verbatim into the master; same semantics as in Tater. |
| `module_key`, `required_settings_count`, `autostart_key`, `settings_category`, `tags` | optional (core) | Copied verbatim; `module_key`/`autostart_key` must match what the core's code uses. |

### Release procedure (every release of the source repo)

1. In the .py: bump the class attribute — `version = "1.1.0"` (or `__version__`).
2. In the manifest: set the item's `version` to **the same value**.
3. Recompute the hash: `sha256sum verba/my_new_verba.py` → paste into the item's
   `sha256`.
4. Commit, tag (`v1.1.0`), push to `main`.

Steps 1 and 2 moving apart = updates silently never appear. Step 3 missing = installs
fail with "SHA256 mismatch". Do all four together.

## Part 2 — register it in the master (this repo)

### 1. One entry in `repos.json`

```json
{
  "owner": "heapsoftware",
  "repo": "Tater-My-New-Thing",
  "branch": "main",
  "manifest": "manifest.json"
}
```

- `owner` / `repo`: exactly as in the repo's GitHub URL.
- `branch`: the branch the manifest is released on (usually `main`).
- `manifest`: `manifest.json` for verba repos, `core_manifest.json` for core repos.
- Put the entry in `verba_repos` or `core_repos` accordingly. (JSON has no comments —
  don't try.)

### 2. Verify locally

```sh
python3 build_manifest.py --check-only
```

Expected: a new row in the table with `SHA: ok`. If it fails, the per-letter meaning:

| Check | What it caught | Fix |
|---|---|---|
| **A** | id duplicated across your source repos | make the id unique |
| **B** | id exists in the official Tater_Shop (yours would be hidden) | pick a different id |
| **C** (warn) | version not `X.Y[.Z]` — Tater would compare it as 0.0.0 | use a plain semver |
| **D** | sha256 missing / not 64 hex | recompute (Part 1, step 3) |
| **E** | downloaded file's hash ≠ manifest sha (stale hash, or the file isn't pushed yet) | re-hash; **push the source repo first** — the master can only index what's on GitHub; if you just pushed, wait ~5 min (raw CDN lag) and retry |
| **F** (warn) | .py class version ≠ manifest version — the update button will never appear | Part 1, steps 1+2 together |

A fetch/parse error of the source manifest aborts the whole run by design — a repo is
never silently dropped from the index.

### 3. Build, review, push

```sh
python3 build_manifest.py     # rewrites entries, runs all checks, writes manifest.json
git diff                      # should be ONLY the new item (or version/sha bumps)
```

Then commit + push (the owner's rule: explicit yes per push). **Shortcut:** if the
source repo is already pushed, you can push just the `repos.json` change and let the
auto rollup (`.github/workflows/rollup.yml`, every 30 min) generate the manifest.

## Part 3 — Tater side

- Nothing to do per new verba repo — the item appears in the shop on the next view
  (the master URL is already registered).
- **First core ever added to the master?** Paste the master URL into the Cores page's
  *Custom repositories* too (same URL as the Verbas page).
- Verify: item appears under the "Tater Modules" source name; install it; on a later
  release, the update button appears after the master manifest's version is bumped.
- Remember §README: remove any old per-repo manifest URLs from the custom-repo list —
  they load before the master and shadow it on shared ids.

## Troubleshooting (symptom → cause → fix)

| Symptom in Tater | Cause | Fix |
|---|---|---|
| "SHA256 mismatch" on install/update | master sha ≠ actual file bytes (stale hash, or CDN lag right after a source push) | rebuild with `--check-only` first; if hashes are right, wait ~5 min for the raw CDN and retry |
| Update button never appears after a source release | manifest `version` not bumped (or class attribute not bumped) | fix the version pairing in the source repo, rebuild master |
| An item missing from the shop | id collides with the official Tater_Shop, or the source manifest fetch is erroring | check B / the per-source error line in the UI |
| Item installs but Tater treats it as a new plugin | `id` changed between master versions | restore the old id |
| Whole "Tater Modules" source shows an error | manifest URL 404 / JSON broken / top-level not an object | validate locally with `--check-only` |

## Checklist (per new repo, first time only)

- [ ] Source repo: public, `main` branch, .py file in place
- [ ] Source repo: schema-1 manifest at root with item: `id` (unique, stable), `name`,
      `version` == class attribute, relative `entry`, correct `sha256`
- [ ] Source repo: committed + pushed
- [ ] `repos.json`: entry added to the right list
- [ ] `python3 build_manifest.py --check-only` → new row, SHA ok
- [ ] Full build → `git diff` shows only the new item → commit + push
- [ ] Tater: item visible in the shop; first core ever → URL pasted on Cores page too
