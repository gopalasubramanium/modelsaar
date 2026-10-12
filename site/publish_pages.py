#!/usr/bin/env python3
"""Maintain the generated-output branch `gh-pages` for GitHub Pages branch publishing.

    python site/publish_pages.py build                      # build production from HEAD, commit to gh-pages
    python site/publish_pages.py rollback <gh-pages-commit> # restore a previous generated build as a new commit
    python site/publish_pages.py log                        # list gh-pages commits with their source revisions

The branch holds ONLY the static output plus the files Pages needs: `.nojekyll`, `CNAME` (custom
domain for branch publishing), `BUILD-INFO.json` (source revision, generator revision, build time,
checksum of the output) and `robots.txt`/`sitemap.xml` from the build. Every publication is a new commit
whose message names the source commit, so the branch history is the deployment history and any earlier
build can be restored verbatim by `rollback` (which checks out that commit's tree into a NEW commit — the
history is never rewritten and no branch is force-pushed). Pushing `gh-pages` is what deploys.

Safety: the build consumes ONLY the committed tree of HEAD — `git archive HEAD` is exported to a
temporary directory and the generator runs from there, so an untracked, ignored or modified file in
the working tree (e.g. a stray file under site/static/) can never enter an output that claims an
exact source commit. A dirty tree (tracked modifications) is refused so the operator does not build
a revision they did not mean to. `rollback` verifies the target commit is on gh-pages and carries a
BUILD-INFO.json.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BRANCH = "gh-pages"
DOMAIN = "modelsaar.com"


def git(*args: str, cwd: Path = ROOT, check: bool = True) -> str:
    return subprocess.run(["git", *args], cwd=cwd, text=True, capture_output=True, check=check).stdout.strip()


def tree_hash(path: Path) -> str:
    h = hashlib.sha256()
    for f in sorted(p for p in path.rglob("*") if p.is_file() and ".git" not in p.parts):
        h.update(str(f.relative_to(path)).encode())
        h.update(f.read_bytes())
    return h.hexdigest()


def branch_exists() -> bool:
    return subprocess.run(["git", "rev-parse", "--verify", "-q", BRANCH], cwd=ROOT, capture_output=True).returncode == 0


def commit_tree(workdir: Path, message: str) -> str:
    """Create a commit on gh-pages whose tree is the contents of workdir (no checkout of the main tree)."""
    with tempfile.TemporaryDirectory() as idx:
        env = {**os.environ, "GIT_INDEX_FILE": str(Path(idx) / "index")}
        subprocess.run(["git", "--work-tree", str(workdir), "add", "-A", "."], cwd=ROOT, env=env, check=True)
        tree = subprocess.run(["git", "write-tree"], cwd=ROOT, env=env, text=True, capture_output=True, check=True).stdout.strip()
    parent = git("rev-parse", BRANCH) if branch_exists() else None
    args = ["commit-tree", tree, "-m", message] + (["-p", parent] if parent else [])
    commit = git(*args)
    git("update-ref", f"refs/heads/{BRANCH}", commit)
    return commit


def export_commit(commit: str, dest: Path) -> None:
    """Materialise the committed tree of ``commit`` under ``dest`` (nothing from the working tree)."""
    tar = subprocess.run(["git", "archive", "--format=tar", commit], cwd=ROOT, capture_output=True, check=True).stdout
    subprocess.run(["tar", "-x", "-C", str(dest)], input=tar, check=True)


def build() -> int:
    if git("status", "--porcelain", "--untracked-files=no"):
        print("refusing: working tree has uncommitted changes to tracked files (commit them, or stash; the build uses the committed tree only)")
        return 2
    src = git("rev-parse", "HEAD")
    untracked = git("status", "--porcelain", "--untracked-files=all", "--", "site")
    if untracked:
        print(f"note: {len(untracked.splitlines())} untracked file(s) under site/ are NOT part of this build (it uses the committed tree only)")
    export = Path(tempfile.mkdtemp(prefix="modelsaar-site-src-"))
    out = Path(tempfile.mkdtemp(prefix="modelsaar-pages-"))
    try:
        export_commit(src, export)
        # The generator records the commit and per-page lastmod from git; point it at this repository's
        # history while its files come from the immutable export.
        env = {**os.environ, "GIT_DIR": str(ROOT / ".git"), "GIT_WORK_TREE": str(export)}
        subprocess.run([sys.executable, str(export / "site/build.py"), "--out", str(out)], check=True, env=env, cwd=export)
        subprocess.run([sys.executable, str(export / "site/check_site.py"), str(out)], check=True, env=env, cwd=export)
        (out / ".nojekyll").write_text("")
        (out / "CNAME").write_text(DOMAIN + "\n")
        info = {
            "source_commit": src,
            "source_branch": git("rev-parse", "--abbrev-ref", "HEAD"),
            "source_tree": git("rev-parse", f"{src}^{{tree}}"),
            "inputs": "git archive of source_commit (committed files only)",
            "generator": "site/build.py",
            "built_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "output_sha256": tree_hash(out),
            "installer_pin": next((ln.split(":-")[1].rstrip('}"') for ln in (out / "install.sh").read_text().splitlines() if ln.startswith('REF="')), None),
            "canonical": f"https://{DOMAIN}",
        }
        (out / "BUILD-INFO.json").write_text(json.dumps(info, indent=2) + "\n")
        commit = commit_tree(out, f"site build from {src[:12]} ({info['built_at']})\n\nsource_commit: {src}\noutput_sha256: {info['output_sha256']}")
    finally:
        shutil.rmtree(out, ignore_errors=True)
        shutil.rmtree(export, ignore_errors=True)
    print(f"gh-pages {commit[:12]} <- source {src[:12]} output {info['output_sha256'][:12]}")
    return 0


def rollback(target: str) -> int:
    if not branch_exists():
        print("no gh-pages branch yet: nothing to roll back to")
        return 2
    full = git("rev-parse", "--verify", f"{target}^{{commit}}")
    if subprocess.run(["git", "merge-base", "--is-ancestor", full, BRANCH], cwd=ROOT).returncode != 0:
        print(f"refusing: {full[:12]} is not on {BRANCH}")
        return 2
    try:
        info = json.loads(git("show", f"{full}:BUILD-INFO.json"))
    except subprocess.CalledProcessError:
        print(f"refusing: {full[:12]} has no BUILD-INFO.json (not a build produced by this script)")
        return 2
    work = Path(tempfile.mkdtemp(prefix="modelsaar-rollback-"))
    tar = subprocess.run(["git", "archive", full], cwd=ROOT, capture_output=True, check=True).stdout
    subprocess.run(["tar", "-x", "-C", str(work)], input=tar, check=True)
    commit = commit_tree(work, f"rollback to gh-pages {full[:12]} (source {info['source_commit'][:12]})\n\nrestores_build: {full}\nsource_commit: {info['source_commit']}\noutput_sha256: {info['output_sha256']}")
    shutil.rmtree(work, ignore_errors=True)
    print(f"gh-pages {commit[:12]} restores build {full[:12]} (source {info['source_commit'][:12]})")
    return 0


def log() -> int:
    if not branch_exists():
        print("no gh-pages branch")
        return 0
    for line in git("log", "--format=%H %cs %s", BRANCH).splitlines():
        sha = line.split()[0]
        try:
            info = json.loads(git("show", f"{sha}:BUILD-INFO.json"))
            print(f"{sha[:12]}  source {info['source_commit'][:12]}  output {info['output_sha256'][:12]}  {line.split(' ', 2)[2]}")
        except subprocess.CalledProcessError:
            print(f"{sha[:12]}  (no BUILD-INFO)  {line}")
    return 0


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "build"
    if cmd == "build":
        sys.exit(build())
    if cmd == "rollback" and len(sys.argv) > 2:
        sys.exit(rollback(sys.argv[2]))
    if cmd == "log":
        sys.exit(log())
    print(__doc__)
    sys.exit(2)
