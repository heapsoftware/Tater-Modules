# Tater Master Repo

A single "master" Tater shop **index** repo. Instead of adding one custom-repository
manifest URL to Tater per verba/core repo, you add **one** URL (this repo) and Tater can
see, install, and update every item from all source repos.

- `manifest.json` — verba index. **GENERATED — do not hand-edit.**
- `core_manifest.json` — core index. **GENERATED — do not hand-edit.** (Omitted while there
  are no core repos.)
- `repos.json` — hand-edited config, the only source of truth for which source repos are
  merged. One entry per source repo.
- `build_manifest.py` — the merge/verify script (pure stdlib Python 3).

This repo never contains .py files. Each manifest item's `entry` is an absolute raw URL
pointing at the file in its own source repo; Tater downloads straight from there.

## The URLs to paste into Tater

Add these under the Verbas / Cores page → *Custom repositories* (Name optional, Manifest
URL required) in the Tater UI:

- Verbas: `https://raw.githubusercontent.com/heapsoftware/Tater-Modules/main/manifest.json`
- Cores: `https://raw.githubusercontent.com/heapsoftware/Tater-Modules/main/core_manifest.json`
  (only once core repos exist)

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

**On GitHub — nothing to set up, as long as the repo follows the per-repo convention**
(the same one your existing repos already follow):

1. Schema-1 manifest at the repo root: `manifest.json` with a `verbas` array for verba
   repos, `core_manifest.json` with a `cores` array for core repos.
2. Every item carries `id` (stable, unique — never reuse an id and never collide with an
   official Tater_Shop id), `name`, `version`, relative `entry` (path to the .py from the
   repo root), and the `sha256` of that exact file.
3. Normal release process per repo: bump the class `version` *and* the manifest `version`
   to the same value, recompute `sha256sum`, commit/tag/push.
4. The repo is public (or the master repo must have read access via a deploy key).
   Default branch should be `main` (or put the real branch in the config below).

**In this repo — one entry in `repos.json`:**

```json
{
  "owner": "heapsoftware",
  "repo": "Tater-<New-Thing>",
  "branch": "main",
  "manifest": "manifest.json"
}
```

into `verba_repos` (or `core_repos` for cores). Then:

- `python3 build_manifest.py --check-only` — all checks pass for the new repo.
- Full build, review the diff (should be only *added* items), commit, push (or let the
  auto rollup pick it up — it only needs the `repos.json` change pushed).
- First core ever added? Also paste the cores URL into Tater's Cores page (§URLs above).

**Removing a source repo:** delete its entry from `repos.json`, rebuild (its items drop
from the master), push. Copies already installed on Tater devices stay installed.

## Auto rollup (how the master updates itself)

`.github/workflows/rollup.yml` (pushed with this repo) runs the exact step-2 flow —
`build_manifest.py --check-only`, full build, commit, push — automatically:

- **Every 30 minutes** (scheduled) and **on demand** (Actions tab → *rollup* → Run
  workflow). No secrets needed: the workflow token can write to this repo only.
- It retries a failed build up to 6× (60 s apart) because the raw CDN lags source pushes
  by up to ~5 min; a source repo mid-release also fails checks and resolves on retry.
- It commits **only when a manifest actually changed**, so quiet runs cost nothing.

**Optional — instant updates instead of ≤30 min:** add this to each source repo
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

If you'd rather not manage a PAT, skip this — the 30-minute schedule already keeps the
master current within half an hour of any source release.

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
