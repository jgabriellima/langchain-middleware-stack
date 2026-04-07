#!/usr/bin/env python3
"""Release pipeline: semver bump, changelog since last tag, build, twine check, git tag, PyPI, GitHub.

Environment:
  CONFIRM=yes     Required for git push, twine upload, and gh release (unless DRY_RUN=1).
  DRY_RUN=1       Print plan and commands; do not modify files or call remotes.
  BUMP=auto|major|minor|patch|none
                  auto: conventional commits since last tag (feat! / BREAKING -> major,
                  feat -> minor, else patch). none: keep pyproject version.
  SKIP_TESTS=1    Do not run pytest before build.
  SKIP_PYPI=1     Skip twine upload.
  SKIP_GH=1       Skip gh release create.
"""
from __future__ import annotations

import argparse
import importlib.util
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = ROOT / "pyproject.toml"
VERSION_RE = re.compile(r'^version\s*=\s*"([^"]+)"', re.MULTILINE)
SEMVER_TAG_RE = re.compile(r"^v(?P<maj>\d+)\.(?P<min>\d+)\.(?P<pat>\d+)$")
CONVENTIONAL_BREAKING_RE = re.compile(
    r"^(\w+)(\([^)]*\))?!:|BREAKING CHANGE", re.IGNORECASE | re.MULTILINE
)
CONVENTIONAL_FEAT_RE = re.compile(r"^feat(\(|:)", re.IGNORECASE)


def run(cmd: list[str], *, cwd: Path = ROOT, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=cwd,
        text=True,
        capture_output=True,
        check=check,
    )


def run_out(cmd: list[str], *, cwd: Path = ROOT) -> str:
    p = run(cmd, cwd=cwd)
    return (p.stdout or "").strip()


def die(msg: str, code: int = 1) -> None:
    print(f"release_publish: {msg}", file=sys.stderr)
    sys.exit(code)


def read_pyproject_version() -> str:
    text = PYPROJECT.read_text(encoding="utf-8")
    m = VERSION_RE.search(text)
    if not m:
        die(f"could not find version in {PYPROJECT}")
    return m.group(1)


def write_pyproject_version(new_version: str) -> None:
    text = PYPROJECT.read_text(encoding="utf-8")
    new_text, n = VERSION_RE.subn(f'version = "{new_version}"', text, count=1)
    if n != 1:
        die(f"failed to replace version in {PYPROJECT}")
    PYPROJECT.write_text(new_text, encoding="utf-8")


def parse_semver(v: str) -> tuple[int, int, int]:
    m = re.match(r"^(\d+)\.(\d+)\.(\d+)(?:[a-zA-Z0-9.-]*)?$", v.strip())
    if not m:
        die(f"not a plain semver X.Y.Z: {v!r}")
    return int(m.group(1)), int(m.group(2)), int(m.group(3))


def format_semver(t: tuple[int, int, int]) -> str:
    return f"{t[0]}.{t[1]}.{t[2]}"


def bump_version(current: str, kind: str) -> str:
    maj, min_, pat = parse_semver(current)
    if kind == "major":
        return format_semver((maj + 1, 0, 0))
    if kind == "minor":
        return format_semver((maj, min_ + 1, 0))
    if kind == "patch":
        return format_semver((maj, min_, pat + 1))
    die(f"unknown bump kind: {kind!r}")


def latest_semver_tag() -> str | None:
    out = run_out(
        ["git", "tag", "-l", "--sort=-v:refname", "v*.*.*"],
    )
    if not out:
        return None
    for line in out.splitlines():
        tag = line.strip()
        if SEMVER_TAG_RE.match(tag):
            return tag
    return None


def git_clean() -> bool:
    out = run_out(["git", "status", "--porcelain"])
    return len(out) == 0


def commits_since(ref: str | None) -> list[str]:
    if ref is None:
        rng: list[str] = ["HEAD"]
    else:
        rng = [f"{ref}..HEAD"]
    out = run_out(["git", "log", *rng, "--pretty=format:%s"])
    if not out:
        return []
    return [ln.strip() for ln in out.splitlines() if ln.strip()]


def infer_bump_from_messages(subjects: list[str]) -> str:
    for subj in subjects:
        if CONVENTIONAL_BREAKING_RE.search(subj):
            return "major"
    for subj in subjects:
        if CONVENTIONAL_FEAT_RE.match(subj):
            return "minor"
    return "patch"


def changelog_block(since_tag: str | None, new_version: str) -> str:
    if since_tag:
        log = run_out(
            ["git", "log", f"{since_tag}..HEAD", "--pretty=format:* %s (%h)"],
        )
        header = f"## {new_version}\n\nChanges since `{since_tag}`:\n\n"
    else:
        log = run_out(["git", "log", "--pretty=format:* %s (%h)"])
        header = f"## {new_version}\n\nChanges (no previous semver tag in repo):\n\n"
    body = log if log else "* (no commits in range)\n"
    return header + body + "\n"


def require_tools(skip_pypi: bool, skip_gh: bool) -> None:
    if not shutil.which("git"):
        die("git not found on PATH")
    if not skip_pypi:
        # Twine is invoked as `python -m twine`; venvs often have no `twine` on PATH.
        if importlib.util.find_spec("twine") is None:
            die(
                "twine is not importable in this Python; install dev extras: "
                "uv pip install --python .venv/bin/python -e '.[dev]'"
            )
    if not skip_gh and os.environ.get("DRY_RUN") != "1":
        if not shutil.which("gh"):
            die("gh CLI not found; install https://cli.github.com/ or set SKIP_GH=1")


def _bump_from_env() -> str:
    v = (os.environ.get("BUMP") or "").strip().lower()
    if v in ("auto", "major", "minor", "patch", "none"):
        return v
    return "auto"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--bump",
        default=_bump_from_env(),
        choices=("auto", "major", "minor", "patch", "none"),
        help="Semver bump (env BUMP overrides if set to a valid value)",
    )
    args = parser.parse_args()
    bump = args.bump

    dry = os.environ.get("DRY_RUN") == "1"
    confirm = os.environ.get("CONFIRM") == "yes"
    skip_tests = os.environ.get("SKIP_TESTS") == "1"
    skip_pypi = os.environ.get("SKIP_PYPI") == "1"
    skip_gh = os.environ.get("SKIP_GH") == "1"

    if not dry and not confirm:
        die(
            "Refusing to push/upload without CONFIRM=yes. "
            "Use DRY_RUN=1 to preview, or CONFIRM=yes after reviewing the plan."
        )

    if not dry and not git_clean():
        die("working tree is not clean; commit or stash before publishing")

    tag = latest_semver_tag()
    if tag is None:
        print(
            "  Note: no semver tag v*.*.* yet. "
            "For a first release at the current pyproject version, use BUMP=none."
        )
    subjects = commits_since(tag)
    if tag and not subjects:
        die(f"no commits after {tag}; nothing new to release")

    current = read_pyproject_version()
    if tag:
        tag_ver = tag[1:] if tag.startswith("v") else tag
        if tag_ver != current:
            print(
                f"  WARNING: latest semver tag is {tag!r} ({tag_ver}) but "
                f"pyproject.toml version is {current!r}; bump uses pyproject as the base."
            )
    if bump == "auto":
        kind = infer_bump_from_messages(subjects)
        print(f"  BUMP=auto inferred as {kind!r} from conventional commit subjects.")
    elif bump == "none":
        kind = None
    else:
        kind = bump

    new_version = current if kind is None else bump_version(current, kind)
    if new_version == current and kind is not None:
        print(f"  Version unchanged ({current}); still proceeding with build/check.")

    notes = changelog_block(tag, new_version)
    print("\n--- Release notes (preview) ---\n")
    print(notes)
    print("--- end preview ---\n")

    if dry:
        print("DRY_RUN=1: skipping file changes, build, git, PyPI, and GitHub.")
        return

    require_tools(skip_pypi, skip_gh)

    tag_name = f"v{new_version}"
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        suffix=".md",
        delete=False,
        prefix="release_notes_",
    ) as tmp:
        tmp.write(notes)
        tmp.flush()
        notes_path = Path(tmp.name)

    try:
        if new_version != current:
            write_pyproject_version(new_version)
            print(f"  Updated {PYPROJECT.name} -> version = {new_version!r}")

        msg = f"chore: release {new_version}"
        subprocess.run(["git", "add", "pyproject.toml"], cwd=ROOT, check=True)
        staged = subprocess.run(
            ["git", "diff", "--cached", "--quiet"],
            cwd=ROOT,
        )
        if staged.returncode != 0:
            subprocess.run(["git", "commit", "-m", msg], cwd=ROOT, check=True)
        else:
            print("  No pyproject version change to commit (already at release version).")

        existing = run_out(["git", "tag", "-l", tag_name])
        if existing == tag_name:
            print(f"  Tag {tag_name} already exists locally; skipping git tag.")
        else:
            subprocess.run(["git", "tag", "-a", tag_name, "-m", msg], cwd=ROOT, check=True)

        if not skip_tests:
            print("  Running pytest…")
            subprocess.run(
                [sys.executable, "-m", "pytest", "tests/", "-q"],
                cwd=ROOT,
                check=True,
            )

        dist = ROOT / "dist"
        if dist.exists():
            shutil.rmtree(dist)

        print("  python -m build")
        subprocess.run([sys.executable, "-m", "build"], cwd=ROOT, check=True)

        def dist_release_files() -> list[Path]:
            return sorted(dist.glob("*.tar.gz")) + sorted(dist.glob("*.whl"))

        artifacts = dist_release_files()
        if not artifacts:
            die("build produced no wheel/sdist under dist/")
        print("  twine check …")
        subprocess.run(
            [sys.executable, "-m", "twine", "check", *[str(p) for p in artifacts]],
            cwd=ROOT,
            check=True,
        )

        print("  git push origin HEAD")
        subprocess.run(["git", "push", "origin", "HEAD"], cwd=ROOT, check=True)
        print(f"  git push origin {tag_name}")
        subprocess.run(["git", "push", "origin", tag_name], cwd=ROOT, check=True)

        if not skip_pypi:
            print("  twine upload …")
            subprocess.run(
                [sys.executable, "-m", "twine", "upload", *[str(p) for p in artifacts]],
                cwd=ROOT,
                check=True,
            )
        else:
            print("  SKIP_PYPI=1: skipping twine upload.")

        if not skip_gh:
            cmd = [
                "gh",
                "release",
                "create",
                tag_name,
                "--title",
                tag_name,
                "--notes-file",
                str(notes_path),
            ]
            cmd.extend(str(p) for p in artifacts)
            subprocess.run(cmd, cwd=ROOT, check=True)
        else:
            print("  SKIP_GH=1: skipping GitHub release.")

        print(f"\n  Done. Released {new_version} ({tag_name}).")
    finally:
        notes_path.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
