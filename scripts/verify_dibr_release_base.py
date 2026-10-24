#!/usr/bin/env python3
"""Verify the exact stable-release base and unchanged dependency lock."""

import argparse
import json
import os
import re
import subprocess
from pathlib import Path

EXPECTED_REPOSITORY = "liviutrn/UEVR-Quad-Views-Mono"
EXPECTED_RELEASE_TAG = "v186.1-mpc-hud-eyealignment-persist49-56"
EXPECTED_RELEASE_COMMIT = "60d0aae86949723d21266e4121a833f0191729c2"
EXPECTED_RELEASE_ASSET_SHA256 = "23c0d0b005c55d4379df3079e6652016d93ea3e178140988be864183a394a7bc"
EXPECTED_BRANCH = "feature/duoview-dibr-manual-depth-luna-20261024"
EXPECTED_UPSTREAM_COMMITS = {
    "backend": "5ac7edc207866569334175e4ed8a7517971547f6",
    "sdk": "3cffbc82429b6165ceec2714f0f0d9ae48f55596",
    "frontend": "60be4b0f9a646109fd9fdf448bacd41477234091",
}


def git(root, *args):
    return subprocess.check_output(
        ["git", "-C", str(root), *args], text=True
    ).strip()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("workspace", type=Path)
    parser.add_argument("evidence", type=Path)
    args = parser.parse_args()
    root = args.workspace.resolve()
    policy = json.loads((root / "DIBR_RELEASE_BASE.json").read_text())
    expected_policy = {
        "repository": EXPECTED_REPOSITORY,
        "release_tag": EXPECTED_RELEASE_TAG,
        "release_commit": EXPECTED_RELEASE_COMMIT,
        "release_asset_sha256": EXPECTED_RELEASE_ASSET_SHA256,
        "implementation_branch": EXPECTED_BRANCH,
        "upstream_backend_commit": EXPECTED_UPSTREAM_COMMITS["backend"],
        "upstream_sdk_commit": EXPECTED_UPSTREAM_COMMITS["sdk"],
        "upstream_frontend_commit": EXPECTED_UPSTREAM_COMMITS["frontend"],
    }
    for key, value in expected_policy.items():
        if policy.get(key) != value:
            raise RuntimeError(f"DIBR release policy changed its pinned {key}")
    if os.environ.get("GITHUB_ACTIONS") == "true":
        branch = os.environ.get("GITHUB_HEAD_REF") or os.environ.get("GITHUB_REF_NAME")
        if branch != EXPECTED_BRANCH:
            raise RuntimeError(f"CI build ref {branch!r} is not the fresh DIBR branch {EXPECTED_BRANCH}")
    base = EXPECTED_RELEASE_COMMIT
    head = git(root, "rev-parse", "HEAD")
    tag = policy["release_tag"]
    asset_sha256 = policy["release_asset_sha256"].lower()
    if re.fullmatch(r"[0-9a-f]{64}", asset_sha256) is None:
        raise RuntimeError("Accepted release asset SHA256 must contain exactly 64 hex digits")
    try:
        tagged_commit = git(root, "rev-parse", "--verify", f"refs/tags/{tag}^{{commit}}")
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"Accepted release tag is missing: {tag}") from exc
    if tagged_commit != base:
        raise RuntimeError(
            f"Accepted release tag {tag} resolves to {tagged_commit}; expected {base}"
        )
    subprocess.run(
        ["git", "-C", str(root), "merge-base", "--is-ancestor", base, head],
        check=True,
    )
    merge_commits = git(root, "rev-list", "--merges", f"{base}..{head}")
    if merge_commits:
        raise RuntimeError("DIBR development must not merge experimental history")
    lock_path = "duoview/clean_restart/baseline.lock.json"
    expected_lock = json.loads(git(root, "show", f"{base}:{lock_path}"))
    actual_lock = json.loads((root / lock_path).read_text())
    if actual_lock != expected_lock:
        raise RuntimeError("The accepted release's dependency lock changed")
    pinned_commits = {
        "backend": actual_lock["backend"]["commit"],
        "sdk": actual_lock["backend"]["sdk_commit"],
        "frontend": actual_lock["frontend"]["commit"],
    }
    expected_commits = EXPECTED_UPSTREAM_COMMITS
    if pinned_commits != expected_commits:
        raise RuntimeError(
            f"Release provenance disagrees with dependency lock: {pinned_commits}"
        )
    changed_paths = git(root, "diff", "--name-only", base, head).splitlines()
    report = {
        "schema_version": 1,
        "repository": policy["repository"],
        "implementation_branch": policy["implementation_branch"],
        "release_tag": tag,
        "release_commit": base,
        "release_tag_commit": tagged_commit,
        "release_asset_sha256": asset_sha256,
        "release_verified_on": policy["release_verified_on"],
        "build_commit": head,
        "release_is_ancestor": True,
        "merge_commits_after_release": [],
        "upstream_dependency_lock_unchanged": True,
        "upstream_commits": expected_commits,
        "changed_paths_from_release": changed_paths,
        "scope": "Source provenance only; no runtime, live-game, or headset validation",
    }
    args.evidence.mkdir(parents=True, exist_ok=True)
    (args.evidence / "dibr-release-provenance.json").write_text(
        json.dumps(report, indent=2) + "\n"
    )
    print(f"Release source verified: tag {tag} at {base}; build commit {head}")


if __name__ == "__main__":
    main()
