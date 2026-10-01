#!/usr/bin/env python3
"""Build the Tater master-repo manifest(s) from per-repo source manifests.

Pure standard library (urllib), no dependencies. Implements the build requirements:

  - fetches each source repo's manifest (hard error on any fetch failure),
  - rewrites every item's `entry` to an absolute URL under entry_base,
  - runs checks A-F (duplicate ids, official-shop id collision, version
    format, sha256 shape, entry integrity, version drift),
  - writes manifest.json / core_manifest.json exactly once, only if every
    check passed (or prints a summary table with --check-only).

Usage:
    python3 build_manifest.py [--check-only] [--entry-base OVERRIDE] [--no-verify-entries]
"""

import argparse
import hashlib
import json
import os
import re
import sys
import urllib.parse
import urllib.request

SCHEMA = 1
TIMEOUT = 15
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPOS_PATH = os.path.join(SCRIPT_DIR, "repos.json")

# Official Tater_Shop manifests (spec 4.3). Items whose ids collide with
# these are silently hidden by Tater's first-source-wins dedup (check B).
OFFICIAL_MANIFESTS = {
    "verbas": "https://raw.githubusercontent.com/TaterTotterson/Tater_Shop/main/manifest.json",
    "cores": "https://raw.githubusercontent.com/TaterTotterson/Tater_Shop/main/core_manifest.json",
}

VERSION_RE = re.compile(r"^v?\d+(\.\d+){0,2}$")
SHA_RE = re.compile(r"^[0-9a-fA-F]{64}$")
ABS_URL_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*://")
# First class-level (4-space indent) `version = "..."` / `__version__ = "..."`.
CLASS_VERSION_RE = re.compile(
    r"^\s{4}(?:__version__|version)\s*=\s*[\"']([^\"']+)[\"']", re.MULTILINE
)

# (item kind key, repos.json key, output file)
OUTPUTS = (
    ("verbas", "verba_repos", "manifest.json"),
    ("cores", "core_repos", "core_manifest.json"),
)


class BuildError(Exception):
    """Fatal, immediate: config, fetch, or source-manifest validation problem."""


def fetch_bytes(url):
    """Fetch bytes from an http(s):// or file:// URL, or a bare local path."""
    if url.startswith(("http://", "https://")):
        req = urllib.request.Request(url, headers={"User-Agent": "tater-master-build/1.0"})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return resp.read()
    if url.startswith("file://"):
        path = urllib.parse.urlparse(url).path
    else:
        path = url
    with open(path, "rb") as f:
        return f.read()


def load_repos(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        raise BuildError(f"cannot load {path}: {e}")
    if not isinstance(cfg, dict) or cfg.get("schema") != SCHEMA:
        raise BuildError("repos.json: top level must be a JSON object with \"schema\": 1")
    if not isinstance(cfg.get("entry_base"), str) or not cfg["entry_base"].strip():
        raise BuildError("repos.json: \"entry_base\" must be a non-empty string")
    for key in ("verba_repos", "core_repos"):
        repos = cfg.get(key, [])
        if not isinstance(repos, list):
            raise BuildError(f"repos.json: \"{key}\" must be a list")
        for i, r in enumerate(repos):
            if not isinstance(r, dict):
                raise BuildError(f"repos.json: {key}[{i}] must be an object")
            for field in ("owner", "repo", "branch", "manifest"):
                v = r.get(field)
                if not isinstance(v, str) or not v.strip():
                    raise BuildError(f"repos.json: {key}[{i}].{field} must be a non-empty string")
    if not cfg.get("verba_repos") and not cfg.get("core_repos"):
        raise BuildError("repos.json: at least one of verba_repos / core_repos must be non-empty")
    return cfg


def validate_source_manifest(data, kind, src_url):
    """Return the source manifest's items list, or raise BuildError."""
    if not isinstance(data, dict):
        raise BuildError(f"source manifest {src_url}: top level must be a JSON object")
    if data.get("schema") != SCHEMA:
        raise BuildError(f"source manifest {src_url}: \"schema\" must be 1")
    items = data.get(kind)
    if not isinstance(items, list) or not items:
        raise BuildError(f"source manifest {src_url}: needs a non-empty \"{kind}\" array")
    problems = []
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            problems.append(f"item {i}: not a JSON object")
            continue
        label = item.get("id") or f"#{i}"
        for field in ("id", "entry", "version", "sha256"):
            v = item.get(field)
            if not isinstance(v, str) or not v.strip():
                problems.append(f"item {label}: missing or empty \"{field}\"")
        sha = item.get("sha256")
        if isinstance(sha, str) and sha.strip() and not SHA_RE.match(sha):
            problems.append(f"item {label}: sha256 is not 64 hex chars")
    if problems:
        raise BuildError(f"invalid {kind} manifest {src_url}:\n  " + "\n  ".join(problems))
    return items


def make_entry(base, owner, repo, branch, entry):
    """Absolute entry URL per spec 5.2; absolute URLs pass through unchanged."""
    if ABS_URL_RE.match(entry):
        return entry
    return "/".join([base.rstrip("/"), owner, repo, branch, entry.lstrip("/")])


def norm_version(v):
    v = v.strip()
    if v[:1] in ("v", "V"):
        v = v[1:]
    return v


_official_cache = {}


def official_ids(kind):
    """Set of ids in the official shop manifest for kind, or None if unreachable."""
    if kind in _official_cache:
        return _official_cache[kind]
    ids = None
    try:
        data = json.loads(fetch_bytes(OFFICIAL_MANIFESTS[kind]).decode("utf-8"))
        items = data.get(kind) if isinstance(data, dict) else None
        if isinstance(items, list):
            ids = {it.get("id") for it in items if isinstance(it, dict) and it.get("id")}
    except Exception:
        ids = None
    _official_cache[kind] = ids
    return ids


def build_kind(kind, repos, base):
    """Fetch + rewrite one kind. Returns (collected, table_rows, errors, warnings).

    collected: list of (source_label, item-with-rewritten-entry)
    table_rows: list of (id, source_label, version, sha_status)
    """
    collected = []
    table_rows = []
    errors = []
    warnings = []

    for r in repos:
        src_url = "/".join(
            [base.rstrip("/"), r["owner"], r["repo"], r["branch"], r["manifest"]]
        )
        label = f"{r['owner']}/{r['repo']} ({r['branch']})"
        try:
            raw = fetch_bytes(src_url)
            data = json.loads(raw.decode("utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as e:
            raise BuildError(f"cannot fetch {label} manifest: {src_url}\n  {e}")
        try:
            src_items = validate_source_manifest(data, kind, src_url)
        except BuildError as e:
            raise
        for item in src_items:
            new_item = dict(item)
            new_item["entry"] = make_entry(base, r["owner"], r["repo"], r["branch"], item["entry"])
            collected.append((label, new_item))

    # A. duplicate ids across all source repos.
    seen = {}
    for label, item in collected:
        iid = item["id"]
        if iid in seen:
            errors.append(
                f"[A] duplicate id \"{iid}\": present in both {seen[iid]} and {label}"
            )
        else:
            seen[iid] = label

    # B. official shop id collision (first-source-wins dedup would hide ours).
    ids = official_ids(kind)
    if ids is None:
        warnings.append(
            f"[B] official {kind} manifest unreachable; skipped id-collision check"
        )
    else:
        for label, item in collected:
            if item["id"] in ids:
                errors.append(
                    f"[B] id \"{item['id']}\" (from {label}) already exists in the official "
                    f"Tater_Shop and would be silently hidden"
                )

    # C. version format; E. entry integrity; F. version drift.
    for label, item in collected:
        iid = item["id"]
        if not VERSION_RE.match(item["version"]):
            warnings.append(
                f"[C] {iid} ({label}): version {item['version']!r} is not "
                f"semver-like; Tater will compare it as 0.0.0"
            )
        sha_status = "not checked"
        if not NO_VERIFY_ENTRIES:
            entry_url = item["entry"]
            try:
                data = fetch_bytes(entry_url)
            except OSError as e:
                errors.append(f"[E] {iid} ({label}): cannot download entry {entry_url}: {e}")
                sha_status = "unreachable"
            else:
                actual = hashlib.sha256(data).hexdigest()
                expected = item["sha256"].lower()
                if actual == expected:
                    sha_status = "ok"
                else:
                    sha_status = "MISMATCH"
                    errors.append(
                        f"[E] {iid} ({label}): sha256 mismatch — manifest has {expected}, "
                        f"file has {actual} ({entry_url})"
                    )
                m = CLASS_VERSION_RE.search(data.decode("utf-8", "replace"))
                if m and norm_version(m.group(1)) != norm_version(item["version"]):
                    warnings.append(
                        f"[F] {iid} ({label}): class version {m.group(1)!r} differs from "
                        f"manifest version {item['version']!r} — the update button will not "
                        f"appear until they match"
                    )
        table_rows.append((iid, label, item["version"], sha_status))

    return collected, table_rows, errors, warnings


def diff_summary(out_path, new_items, new_doc_header):
    """Human-readable change summary vs the previously written file, if any."""
    if not os.path.exists(out_path):
        return [f"{os.path.basename(out_path)}: new file ({len(new_items)} items)"]
    try:
        with open(out_path, "r", encoding="utf-8") as f:
            old = json.load(f)
        old_items = old.get("verbas") or old.get("cores") or []
        old_by_id = {it["id"]: it for it in old_items if isinstance(it, dict)}
    except (OSError, json.JSONDecodeError):
        return [f"{os.path.basename(out_path)}: previous file unreadable; full rewrite"]
    new_by_id = {it["id"]: it for it in new_items}
    lines = []
    item_key = "verbas" if "verbas" in old else "cores"
    header = {k: v for k, v in old.items() if k != item_key}
    if header != new_doc_header:
        lines.append(
            "  header changed: "
            + ", ".join(
                f"{k}: {header.get(k)!r} -> {new_doc_header[k]!r}"
                for k in sorted(set(header) | set(new_doc_header))
                if header.get(k) != new_doc_header.get(k)
            )
        )
    added = sorted(set(new_by_id) - set(old_by_id))
    removed = sorted(set(old_by_id) - set(new_by_id))
    for iid in sorted(set(new_by_id) & set(old_by_id)):
        if old_by_id[iid] != new_by_id[iid]:
            changed = [
                k
                for k in sorted(set(old_by_id[iid]) | set(new_by_id[iid]))
                if old_by_id[iid].get(k) != new_by_id[iid].get(k)
            ]
            lines.append(f"  changed {iid}: {', '.join(changed)}")
    if added:
        lines.append(f"  added: {', '.join(added)}")
    if removed:
        lines.append(f"  removed: {', '.join(removed)}")
    if not lines:
        lines.append("  no changes")
    header = f"{os.path.basename(out_path)}:"
    return [header] + lines


def main(argv=None):
    global NO_VERIFY_ENTRIES
    ap = argparse.ArgumentParser(
        description="Merge per-repo Tater shop manifests into one master index."
    )
    ap.add_argument(
        "--check-only",
        action="store_true",
        help="run all checks and print a summary table; do not write manifests",
    )
    ap.add_argument(
        "--entry-base", metavar="URL", help="override entry_base from repos.json"
    )
    ap.add_argument(
        "--no-verify-entries",
        action="store_true",
        help="skip downloading entries (checks E and F)",
    )
    args = ap.parse_args(argv)
    NO_VERIFY_ENTRIES = args.no_verify_entries

    try:
        cfg = load_repos(REPOS_PATH)
    except BuildError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    base = args.entry_base or cfg["entry_base"]

    all_errors = []
    all_warnings = []
    outputs = []  # (kind, out_name, items)
    table_rows = []

    for kind, key, out_name in OUTPUTS:
        repos = cfg.get(key) or []
        if not repos:
            continue
        try:
            collected, rows, errors, warnings = build_kind(kind, repos, base)
        except BuildError as e:
            print(f"ERROR: {e}", file=sys.stderr)
            return 1
        all_errors.extend(errors)
        all_warnings.extend(warnings)
        table_rows.extend(rows)
        items = [it for _, it in collected]
        items.sort(key=lambda it: (it.get("name") or "", it.get("id") or ""))
        outputs.append((kind, out_name, items))

    for w in all_warnings:
        print(f"WARNING: {w}")

    if args.check_only:
        print(f"\n{'ID':32} {'SOURCE':42} {'VERSION':10} SHA")
        for iid, label, version, status in table_rows:
            print(f"{iid:32} {label:42} {version:10} {status}")
        print(f"\n{len(table_rows)} items across {len(outputs)} manifest(s).")
        if all_errors:
            for e in all_errors:
                print(f"ERROR: {e}", file=sys.stderr)
            return 1
        print("All checks passed.")
        return 0

    if all_errors:
        for e in all_errors:
            print(f"ERROR: {e}", file=sys.stderr)
        print("\nManifests were NOT written (build in memory, write only on success).")
        return 1

    for kind, out_name, items in outputs:
        doc = {"schema": SCHEMA, "name": cfg.get("name") or "Tater Master Repo", kind: items}
        out_path = os.path.join(SCRIPT_DIR, out_name)
        for line in diff_summary(out_path, items, {k: v for k, v in doc.items() if k != kind}):
            print(line)
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(json.dumps(doc, indent=2) + "\n")
    print(f"\nWrote {len(outputs)} manifest(s). {len(table_rows)} items total.")
    return 0


NO_VERIFY_ENTRIES = False

if __name__ == "__main__":
    sys.exit(main())
