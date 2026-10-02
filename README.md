# Tater Master Repo

A single "master" Tater shop **index** repo. Instead of adding one custom-repository
manifest URL to Tater per verba/core repo, you add **one** URL (this repo) and Tater can
see, install, and update every item from all source repos.

- `manifest.json` — **GENERATED — do not hand-edit.** One file carrying both the `verbas`
  and the `cores` index (Tater's verba store reads `verbas`, the core store reads `cores`,
  each ignoring the other — so this single URL serves both UIs).
- `repos.json` — hand-edited config, the only source of truth for which source repos are
  merged. One entry per source repo. The optional top-level `portals` list (default `[]`)
  is copied verbatim into the generated manifest.
- `build_manifest.py` — the merge/verify script (pure stdlib Python 3).
- `tools/release_notes.py` — writes the auto-release notes (pure stdlib Python 3).

No plugin code lives in this repo. Each manifest item's `entry` is an absolute raw URL
pointing at the file in its own source repo; Tater downloads straight from there.

## The URL to paste into Tater

**One URL, pasted twice.** In the Tater UI, add it under *Custom repositories* (Name
optional, Manifest URL required) on **both** the Verbas page and the Cores page:

`https://raw.githubusercontent.com/heapsoftware/Tater-Modules/main/manifest.json`

It works in both spots because the file contains both a `verbas` and a `cores` list —
each store reads only its own key and ignores the other.

After adding the master URL, **remove the individual per-repo manifest URLs** you
previously added — they load first and would shadow the master's copies on shared ids.

## Day-to-day workflow (2 steps)

**Step 1 — release a source repo** (unchanged, per that repo's own checklist): bump the
plugin class `version` attribute *and* the repo manifest `version` to the same value →
recompute `sha256sum` of the .py → update the repo manifest → commit, tag, push.

**Step 2 — roll up the master** (after any source repo release; batchable):

```sh
python3 build_manifest.py --check-only   # pre-push gate: all checks A–F
python3 build_manifest.py                # rewrites entry URLs, writes the manifests
git diff                                 # should be only version/sha256/entry bumps
```

Review the diff, commit, push. Tater picks the change up automatically on the next shop
view — no Tater-side action needed. (With the auto rollup in §Auto rollup, steps 1–4 of
step 2 run themselves; the manual flow is what the workflow does, and what you do if you
ever need to intervene.)

## Adding a new source repo (when you release a new one)

**Full walkthrough: [`docs/adding-a-source-repo.md`](docs/adding-a-source-repo.md)** —
big picture, manifest templates, field-by-field reference, the release procedure, how to
read every build check, Tater-side steps, troubleshooting, and a per-release checklist.
It is self-contained; no other context needed.

The short version:

1. **GitHub side:** the source repo just follows the per-repo convention — public,
   schema-1 manifest at the root (`manifest.json`/`verbas` or
   `core_manifest.json`/`cores`), each item with a stable unique `id`, `version` equal
   to the .py class attribute, relative `entry`, and the file's `sha256`. No other
   GitHub setup of any kind.
2. **This repo:** one entry in `verba_repos` / `core_repos` of `repos.json`.
3. `python3 build_manifest.py --check-only` → full build → review the `git diff`
   (only the new item) → commit + push. Or push just `repos.json` and let the auto
   rollup generate the manifest within ~15 min.
4. **Tater side:** nothing for verbas; first core ever → paste the master URL on the
   Cores page too.

**Removing a source repo:** delete its entry from `repos.json`, rebuild (its items drop
from the master), push. Copies already installed on Tater devices stay installed.

## Auto rollup (how the master updates itself)

`.github/workflows/rollup.yml` (pushed with this repo) runs the exact step-2 flow —
`build_manifest.py --check-only`, full build, commit, push — automatically:

- **On source change** — dispatched automatically (≤15 min lag) — plus **on push
  to `main`** (e.g. a `repos.json` change) and **on demand** (Actions tab → *rollup*
  → Run workflow). No secrets needed: the workflow token can write to this repo only.
- It retries a failed build up to 6× (60 s apart) because the raw CDN lags source pushes
  by up to ~5 min; a source repo mid-release also fails checks and resolves on retry.
- It commits **only when a manifest actually changed**, so quiet runs cost nothing.

**Optional — push-triggered dispatch, no server dependency:** add this to each source repo
(`.github/workflows/update-master.yml`). `repository_dispatch` crossing repos needs a
token, so create one fine-grained PAT (permission: *Actions: read/write* on
`heapsoftware/Tater-Modules` only), store it as secret `MASTER_DISPATCH_TOKEN` in **each**
source repo, then:

```yaml
name: update-master
on:
  push:
    branches: [main]
jobs:
  dispatch:
    runs-on: ubuntu-latest
    steps:
      - run: |
          curl -sS -X POST \
            -H "Authorization: Bearer $MASTER_DISPATCH_TOKEN" \
            -H "Accept: application/vnd.github+json" \
            https://api.github.com/repos/heapsoftware/Tater-Modules/dispatches \
            -d '{"event_type": "rollup"}'
```

If you'd rather not manage a PAT, skip this — the automatic dispatcher keeps the
master current within ~15 min of any source release.

## Releases (automatic)

Every push that actually changes `repos.json` or `manifest.json` is cut as a GitHub
release by `.github/workflows/release.yml`, which runs right after the auto rollup
finishes (so a regenerated manifest is included before the version is picked):

- Versions are `vMAJOR.MINOR.REVISION`. Automation bumps the **revision** only —
  `v1.0.0 → v1.0.1` — for any index change, including adding or removing a source repo
  or manifest item.
- **MINOR is manual.** When something major happens, cut it yourself:
  `gh release create v1.1.0 --title "v1.1.0" --notes "…"`. The workflow always computes
  the next version from the newest `v*` tag, so a manual release becomes the new base
  and automation continues from there.
- Pushes that leave both data files untouched (docs, workflow tweaks) and quiet
  rollups produce no release — no data change, no release.
- Release notes list exactly which items and source repos were added, removed, or
  version-bumped since the previous tag.

## Local testing without pushing

The build script (like Tater) accepts `file://` URLs and bare local paths for both the
source manifests and the `entry` files, so the whole flow is testable offline:

1. `python3 build_manifest.py --check-only`
2. Build with `--entry-base "file:///abs/path/local-files"` after mirroring the .py files
   under `local-files/`, then point Tater's custom-repo field at
   `file:///abs/path/manifest.json` and confirm install/update.

## Checks the build runs (fail the run unless noted)

| # | Check | On failure |
|---|---|---|
| A | Duplicate ids across the merged master | fail |
| B | Id collision with the official Tater_Shop (official wins dedup, ours would be hidden) | fail (skipped with a warning only if the official manifest is unreachable) |
| C | Version matches `^v?\d+(\.\d+){0,2}$` | **warn** (Tater would compare it as 0.0.0) |
| D | `sha256` present and 64-hex | fail |
| E | Downloaded entry file's sha256 == item sha256 (skip with `--no-verify-entries`) | fail, listing every mismatch |
| F | Downloaded .py's class `version`/`__version__` == item version | **warn** — if they diverge the update button never appears |

A source manifest that fails to fetch or parse aborts the whole run — a repo is never
silently dropped from the master index.
