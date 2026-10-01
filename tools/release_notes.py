#!/usr/bin/env python3
"""Release-notes generator for the master index.

Usage: release_notes.py PREV_REF HEAD_REF OUT_FILE

PREV_REF is a git ref (normally the previous release tag), or "-" for "no
previous release" (everything counts as added). Reads repos.json and
manifest.json at both refs with `git show` and writes markdown release notes
to OUT_FILE. Pure stdlib; run by the release workflow.
"""

import json
import os
import subprocess
import sys


def read_json(ref, path):
    """JSON file at a git ref; None if the ref is "-" or the file is absent."""
    if ref == "-":
        return None
    proc = subprocess.run(
        ["git", "show", f"{ref}:{path}"], capture_output=True, text=True
    )
    if proc.returncode != 0:
        return None  # tag predates the file
    return json.loads(proc.stdout)


def collect_items(data):
    """manifest.json -> {id: (kind, item dict)} across verbas and cores."""
    items = {}
    if data:
        for kind, key in (("verba", "verbas"), ("core", "cores")):
            for item in data.get(key) or []:
                items[str(item.get("id", "?"))] = (kind, item)
    return items


def collect_repos(data):
    """repos.json -> {(kind, 'owner/repo'): (branch, manifest)}."""
    repos = {}
    if data:
        for kind, key in (("verba", "verba_repos"), ("core", "core_repos")):
            for repo in data.get(key) or []:
                slug = f"{repo.get('owner', '?')}/{repo.get('repo', '?')}"
                repos[(kind, slug)] = (repo.get("branch", ""), repo.get("manifest", ""))
    return repos


def item_lines(old, new):
    lines = []
    for item_id in sorted(set(new) - set(old)):
        kind, item = new[item_id]
        lines.append(
            f"- Added {kind} **{item_id}** — {item.get('name', item_id)}"
            f" v{item.get('version', '?')}"
        )
    for item_id in sorted(set(old) - set(new)):
        kind, item = old[item_id]
        lines.append(
            f"- Removed {kind} **{item_id}** — {item.get('name', item_id)}"
            f" (was v{item.get('version', '?')})"
        )
    for item_id in sorted(set(old) & set(new)):
        old_kind, old_item = old[item_id]
        new_kind, new_item = new[item_id]
        if old_item == new_item:
            continue
        name = new_item.get("name", item_id)
        old_ver = old_item.get("version", "?")
        new_ver = new_item.get("version", "?")
        if old_ver == new_ver:
            lines.append(
                f"- Updated {new_kind} **{item_id}** — {name}"
                f" (metadata changed, version unchanged at v{new_ver})"
            )
        else:
            lines.append(
                f"- Updated {new_kind} **{item_id}** — {name}: v{old_ver} → v{new_ver}"
            )
    return lines


def repo_lines(old, new):
    lines = []
    for kind, slug in sorted(set(new) - set(old)):
        lines.append(f"- New {kind} source repo: **{slug}**")
    for kind, slug in sorted(set(old) - set(new)):
        lines.append(f"- Removed {kind} source repo: **{slug}**")
    for key in sorted(set(old) & set(new)):
        if old[key] != new[key]:
            kind, slug = key
            lines.append(f"- Reconfigured {kind} source repo: **{slug}** (branch/manifest)")
    return lines


def short_sha(ref):
    if ref == "-":
        return None
    return subprocess.run(
        ["git", "rev-parse", "--short=7", ref], capture_output=True, text=True, check=True
    ).stdout.strip()


def build_notes(prev_ref, head_ref):
    old_items = collect_items(read_json(prev_ref, "manifest.json"))
    new_items = collect_items(read_json(head_ref, "manifest.json"))
    old_repos = collect_repos(read_json(prev_ref, "repos.json"))
    new_repos = collect_repos(read_json(head_ref, "repos.json"))

    items = item_lines(old_items, new_items)
    repos = repo_lines(old_repos, new_repos)

    sections = []
    if items:
        sections.append("### Manifest items\n\n" + "\n".join(items))
    if repos:
        sections.append("### Source repos\n\n" + "\n".join(repos))
    if not sections:
        sections.append("### Configuration\n\n- Index configuration updated.")

    header = "Initial release of the master index.\n\n" if prev_ref == "-" else ""
    notes = header + "\n\n".join(sections)

    repo_slug = os.environ.get("GITHUB_REPOSITORY")
    prev_sha = short_sha(prev_ref)
    if repo_slug and prev_sha:
        head_sha = short_sha(head_ref)
        notes += (
            f"\n\n**Full diff:** https://github.com/{repo_slug}"
            f"/compare/{prev_sha}...{head_sha}"
        )
    return notes + "\n"


def main(argv):
    if len(argv) != 4:
        print(__doc__, file=sys.stderr)
        return 2
    notes = build_notes(argv[1], argv[2])
    with open(argv[3], "w", encoding="utf-8") as fh:
        fh.write(notes)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
