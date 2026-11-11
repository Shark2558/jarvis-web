# tests/test_github_backfill.py -- R6.1 D4 / decision 4: scripts/github_backfill.sh is a practice
# run by default. Against a stand-in `gh` first on PATH (canned JSON, every call logged) it prints
# one DRY retitle per row of docs/github-backfill.tsv (exactly the 21 titles), never calls a
# write, skips an unmerged pull request, only retitles one that already has its header line, and
# reports one it cannot read. --apply is never run here.
from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "github_backfill.sh"
MAP = ROOT / "docs" / "github-backfill.tsv"
REPO = "Shark2558/jarvis-web"

pytestmark = pytest.mark.skipif(
    shutil.which("bash") is None or shutil.which("jq") is None, reason="needs bash and jq"
)

# A stand-in for `gh api`: logs every call, answers the reads, and records (never makes) a write.
STUB = r"""#!/usr/bin/env bash
printf '%s\n' "$*" >> "$GH_LOG"
[[ "$1" == api ]] || exit 3
shift
for a in "$@"; do [[ "$a" == -X ]] && { echo "WRITE $*" >> "$GH_LOG"; exit 0; }; done
path="$1"
case "$path" in
  */labels/*) exit 1 ;;
  */releases/tags/*) exit 1 ;;
  */pulls/*)
    n="${path##*/}"
    [[ " $STUB_UNREADABLE " == *" $n "* ]] && { echo "HTTP 404: Not Found" >&2; exit 1; }
    merged='"2026-11-01T01:32:42Z"'; [[ " $STUB_UNMERGED " == *" $n "* ]] && merged=null
    body='"The original description."'
    head='"**Version:** v6.0.0 · **Built in:** Mark XII\n\nText"'
    [[ " $STUB_HEADED " == *" $n "* ]] && body="$head"
    printf '{"number": %s, "merged_at": %s, "merge_commit_sha": "%040d", "body": %s}\n' \
      "$n" "$merged" "$n" "$body"
    ;;
  *) exit 4 ;;
esac
"""


@dataclass(frozen=True)
class Row:
    num: str
    version: str
    title: str
    mark: str
    kind: str
    pre: str


@dataclass(frozen=True)
class Run:
    code: int
    out: list[str]
    err: str
    calls: list[str]


def rows() -> list[Row]:
    lines = MAP.read_text(encoding="utf-8").splitlines()
    return [Row(*ln.split("\t")) for ln in lines if ln and not ln.startswith("#")]


def practice(tmp_path: Path, **stub: str) -> Run:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    gh = bin_dir / "gh"
    gh.write_text(STUB, encoding="utf-8")
    gh.chmod(0o755)
    log = tmp_path / "gh.log"
    log.write_text("", encoding="utf-8")
    env = {
        "PATH": f"{bin_dir}{os.pathsep}/usr/bin{os.pathsep}/bin",
        "HOME": str(tmp_path),
        "LC_ALL": "C.UTF-8",  # printf %q keeps the titles' middle dots and dashes readable
        "GH_LOG": str(log),
        **{f"STUB_{k.upper()}": v for k, v in stub.items()},
    }
    done = subprocess.run(
        ["bash", str(SCRIPT)], cwd=ROOT, env=env, capture_output=True, text=True, timeout=120
    )
    calls = log.read_text(encoding="utf-8").splitlines()
    return Run(done.returncode, done.stdout.splitlines(), done.stderr, calls)


# Bash reads back what its own `printf %q` wrote (a body with new lines is $'...' quoted).
UNQUOTE = r"""while IFS= read -r line; do
  eval "set -- $line"; printf '%s\0' "$@"; printf '\036\0'
done"""


def dry(run: Run) -> list[list[str]]:
    """Each DRY line as the argument list it would have run."""
    lines = "".join(ln[len("DRY:") :] + "\n" for ln in run.out if ln.startswith("DRY:"))
    done = subprocess.run(
        ["bash", "-c", UNQUOTE],
        input=lines.encode("utf-8"),
        env={"PATH": "/usr/bin:/bin", "LC_ALL": "C.UTF-8"},
        capture_output=True,
        timeout=60,
        check=True,
    )
    out: list[list[str]] = [[]]
    for word in done.stdout.decode("utf-8").split("\0")[:-1]:
        if word == "\x1e":
            out.append([])
        else:
            out[-1].append(word)
    return out[:-1]


def retitles(run: Run) -> dict[str, list[str]]:
    """PR number -> the DRY PATCH's arguments."""
    out = {}
    for args in dry(run):
        if args[:4] == ["gh", "api", "-X", "PATCH"]:
            out[args[4].rsplit("/", 1)[1]] = args
    return out


def title_of(args: list[str]) -> str:
    return next(a for a in args if a.startswith("title="))[len("title=") :]


def test_the_map_has_the_21_rows() -> None:
    got = rows()
    assert len(got) == 21 and len({r.num for r in got}) == 21
    assert got[-1] == Row(
        "27", "v6.0.0", "v6.0.0 · R6 The Build Book · Mark XII", "XII", "release", "false"
    )


def test_practice_prints_a_dry_retitle_for_exactly_the_21_titles(tmp_path: Path) -> None:
    run = practice(tmp_path)

    assert run.code == 0, run.err
    got = retitles(run)
    assert {n: title_of(a) for n, a in got.items()} == {r.num: r.title for r in rows()}
    assert [ln for ln in run.out if ln.startswith("PR #")] == [
        f"PR #{r.num} → {r.title}" for r in rows()
    ]
    for r in rows():  # the header line goes above the original description
        body = next(a for a in got[r.num] if a.startswith("body="))
        assert body.startswith(f"body=**Version:** {r.version} · **Built in:** Mark {r.mark}")


def test_practice_never_calls_a_write(tmp_path: Path) -> None:
    run = practice(tmp_path)

    assert run.calls, "the stand-in gh was not used"
    assert [c for c in run.calls if c.startswith("WRITE") or "-X" in c.split()] == []
    reads = [c for c in run.calls if re.fullmatch(rf"api repos/{REPO}/pulls/\d+", c)]
    assert len(reads) == 21  # it read every pull request it would change
    verbs = {a[3] for a in dry(run)}
    assert verbs == {"POST", "PATCH"}  # every write was printed instead


def test_practice_labels_and_releases_each_merge_commit(tmp_path: Path) -> None:
    run = practice(tmp_path)
    releases = [a for a in dry(run) if a[4] == f"repos/{REPO}/releases"]
    assert [next(x for x in a if x.startswith("tag_name=")) for a in releases] == [
        f"tag_name={r.version}" for r in rows()
    ]
    for a, r in zip(releases, rows(), strict=True):
        assert f"target_commitish={int(r.num):040d}" in a and f"prerelease={r.pre}" in a
    marks = [a for a in dry(run) if a[4].endswith("/issues/18/labels")]
    assert marks and {"labels[]=Mark VII", "labels[]=Mark VIII", "labels[]=release"} <= set(
        marks[0]
    )


def test_an_unmerged_pull_request_is_skipped(tmp_path: Path) -> None:
    run = practice(tmp_path, unmerged="14")

    assert run.code == 0
    assert "PR #14: not merged, skipped" in run.err
    assert "14" not in retitles(run) and len(retitles(run)) == 20
    joined = "\n".join(run.out)
    assert "/issues/14/" not in joined and "tag_name=v0.9.1" not in joined
    assert not any(ln.startswith("PR #14 ") for ln in run.out)


def test_a_pull_request_that_already_has_its_header_is_only_retitled(tmp_path: Path) -> None:
    run = practice(tmp_path, headed="27")

    args = retitles(run)["27"]
    assert title_of(args) == "v6.0.0 · R6 The Build Book · Mark XII"
    assert not any(a.startswith("body=") for a in args)  # its description is left as it is
    assert any(a.startswith("body=") for a in retitles(run)["26"])


def test_a_pull_request_it_cannot_read_is_reported_and_the_rest_go_on(tmp_path: Path) -> None:
    run = practice(tmp_path, unreadable="26")

    assert run.code == 1  # the practice run says something needs looking at
    assert "PR #26: not readable" in run.err
    assert "26" not in retitles(run) and len(retitles(run)) == 20
    assert [c for c in run.calls if "-X" in c.split()] == []
