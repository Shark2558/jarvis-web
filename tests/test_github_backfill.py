# tests/test_github_backfill.py -- R6.1 D4 / decision 4: scripts/github_backfill.sh is a practice
# run by default. Against a stand-in `gh` first on PATH (canned JSON, every call logged) it prints
# one DRY retitle per row of docs/github-backfill.tsv (exactly the 21 titles), never calls a
# write, skips an unmerged pull request, only retitles one that already has its header line, and
# reports one it cannot read. The stand-in answers only the three reads the script makes and
# refuses every other call (any write flag, any other path); git, curl and wget are stand-ins that
# refuse too. --apply runs only against that stand-in: to show it refuses a repository it wasn't
# confirmed for, and that every write GitHub refuses is reported with what to do by hand, tried
# once, and the run goes on to the end and exits 1 (R6.1 code review M3).
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
# The only calls a practice run may make: `gh api <path>` for a pull request, a label or a tag.
READ = re.compile(rf"api repos/{REPO}/(pulls/\d+|labels/[^ ]+|releases/tags/[^ ]+)")

pytestmark = pytest.mark.skipif(
    shutil.which("bash") is None or shutil.which("jq") is None, reason="needs bash and jq"
)

# A stand-in for `gh api`: logs every call and answers the reads, which take the path alone. Any
# write flag (-X/--method other than GET, -f/-F/--field/--raw-field, --input, in every spelling)
# is logged as WRITE and refused; any other call is logged as ODD and refused.
STUB = r"""#!/usr/bin/env bash
printf '%s\n' "$*" >> "$GH_LOG"
refuse() {  # kind, the call, exit code
  printf '%s %s\n' "$1" "$2" >> "$GH_LOG"; echo "stand-in gh: refused ($1)" >&2; exit "$3"
}
get() { [[ "$1" == [Gg][Ee][Tt] ]]; }
[[ "${1:-}" == api ]] || refuse ODD "$*" 3
shift
all="$*" prev=""
for a in "$@"; do
  if [[ "$prev" == -X || "$prev" == --method ]]; then get "$a" || refuse WRITE "$all" 5; fi
  case "$a" in
    -X?*) v="${a#-X}"; get "${v#=}" || refuse WRITE "$all" 5 ;;
    --method=*) get "${a#--method=}" || refuse WRITE "$all" 5 ;;
    -f*|-F*|--field|--field=*|--raw-field|--raw-field=*|--input|--input=*) refuse WRITE "$all" 5 ;;
  esac
  prev="$a"
done
[[ $# -eq 1 ]] || refuse ODD "$all" 4
path="$1"
case "$path" in
  repos/*/labels/*) exit 1 ;;
  repos/*/releases/tags/*) exit 1 ;;
  repos/*/pulls/*)
    n="${path##*/}"
    [[ " $STUB_UNREADABLE " == *" $n "* ]] && { echo "HTTP 404: Not Found" >&2; exit 1; }
    merged='"2026-11-01T01:32:42Z"'; [[ " $STUB_UNMERGED " == *" $n "* ]] && merged=null
    body='"The original description."'
    head='"**Version:** v6.0.0 · **Built in:** Mark XII\n\nText"'
    [[ " $STUB_HEADED " == *" $n "* ]] && body="$head"
    sha="\"$(printf '%040d' "$n")\""
    [[ " $STUB_NOSHA " == *" $n "* ]] && sha=null
    [[ " $STUB_EMPTYSHA " == *" $n "* ]] && sha='""'
    printf '{"number": %s, "merged_at": %s, "merge_commit_sha": %s, "body": %s}\n' \
      "$n" "$merged" "$sha" "$body"
    ;;
  *) refuse ODD "$all" 4 ;;
esac
"""
# Other tools that could reach GitHub: on PATH before /usr/bin, each logs OTHER and refuses.
OTHER = r"""#!/usr/bin/env bash
printf 'OTHER %s %s\n' "${0##*/}" "$*" >> "$GH_LOG"; exit 7
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


def stand_ins(tmp_path: Path) -> Path:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    for name, text in (("gh", STUB), ("git", OTHER), ("curl", OTHER), ("wget", OTHER)):
        tool = bin_dir / name
        tool.write_text(text, encoding="utf-8")
        tool.chmod(0o755)
    return bin_dir


def practice(
    tmp_path: Path,
    *args: str,
    script: Path = SCRIPT,
    env: dict[str, str] | None = None,
    **stub: str,
) -> Run:
    log = tmp_path / "gh.log"
    log.write_text("", encoding="utf-8")
    full = {
        "PATH": f"{stand_ins(tmp_path)}{os.pathsep}/usr/bin{os.pathsep}/bin",
        "HOME": str(tmp_path),
        "LC_ALL": "C.UTF-8",  # printf %q keeps the titles' middle dots and dashes readable
        "GH_LOG": str(log),
        **{f"STUB_{k.upper()}": v for k, v in stub.items()},
        **(env or {}),
    }
    done = subprocess.run(
        ["bash", str(script), *args],
        cwd=ROOT,
        env=full,
        capture_output=True,
        text=True,
        timeout=120,
    )
    calls = log.read_text(encoding="utf-8").splitlines()
    return Run(done.returncode, done.stdout.splitlines(), done.stderr, calls)


def not_reads(run: Run) -> list[str]:
    """Every logged call that isn't exactly one of the three reads (a write, a stray tool)."""
    return [c for c in run.calls if not READ.fullmatch(c)]


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

    assert run.code == 0 and run.calls, "the stand-in gh was not used"
    assert not_reads(run) == []  # every call is exactly a read: no write flag, no other tool
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
    assert not_reads(run) == []


@pytest.mark.parametrize("stub", ["nosha", "emptysha"])
def test_a_pull_request_without_a_merge_commit_is_reported_and_never_released(
    tmp_path: Path, stub: str
) -> None:
    """Security review L4: a null or empty merge_commit_sha never reaches a Release."""
    run = practice(tmp_path, **{stub: "26"})

    assert run.code == 1
    assert "PR #26: GitHub gave no merge commit, skipped" in run.err
    assert "26" not in retitles(run) and len(retitles(run)) == 20
    joined = "\n".join(run.out)
    assert "/issues/26/" not in joined and "tag_name=v5.1.1" not in joined
    releases = [a for a in dry(run) if a[4] == f"repos/{REPO}/releases"]
    targets = [next(x for x in a if x.startswith("target_commitish=")) for a in releases]
    assert len(targets) == 20
    assert all(re.fullmatch(r"target_commitish=[0-9a-f]{40}", t) for t in targets), targets


# ---- the stand-in itself refuses every write (R6.1 review M2) ----------------------------------
PR1 = f"repos/{REPO}/pulls/1"
WRITE_FORMS = [
    ["-X", "POST", f"repos/{REPO}/labels"],
    ["-X", "patch", PR1],
    ["-XPATCH", PR1],
    ["-X=PATCH", PR1],
    ["--method", "PATCH", PR1],
    ["--method=DELETE", PR1],
    [PR1, "-f", "title=x"],
    [PR1, "-ftitle=x"],
    [PR1, "-F", "prerelease=true"],
    [PR1, "-Fprerelease=true"],
    [PR1, "--field", "title=x"],
    [PR1, "--field=title=x"],
    [PR1, "--raw-field", "title=x"],
    [PR1, "--raw-field=title=x"],
    [PR1, "--input", "body.json"],
    [PR1, "--input=-"],
    ["-X", "GET", PR1, "-f", "q=1"],  # a field counts as a write even with GET
]


def call_stand_in(tmp_path: Path, args: list[str]) -> tuple[int, str, list[str]]:
    log = tmp_path / "gh.log"
    log.write_text("", encoding="utf-8")
    env = {"PATH": "/usr/bin:/bin", "GH_LOG": str(log), "LC_ALL": "C.UTF-8"}
    done = subprocess.run(
        [str(stand_ins(tmp_path) / "gh"), "api", *args],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return done.returncode, done.stdout, log.read_text(encoding="utf-8").splitlines()


@pytest.mark.parametrize("args", WRITE_FORMS, ids=" ".join)
def test_the_stand_in_refuses_every_spelling_of_a_write(tmp_path: Path, args: list[str]) -> None:
    code, out, calls = call_stand_in(tmp_path, args)
    assert code != 0 and out == ""
    assert calls[-1].startswith("WRITE ")


@pytest.mark.parametrize(
    "args",
    [[PR1, "--jq", ".title"], ["-X", "GET", PR1], ["graphql"], [f"repos/{REPO}/issues/1"], []],
    ids=" ".join,
)
def test_the_stand_in_refuses_any_call_but_the_three_reads(tmp_path: Path, args: list[str]) -> None:
    code, out, calls = call_stand_in(tmp_path, args)
    assert code != 0 and out == "" and calls[-1].startswith("ODD ")


def test_the_stand_in_answers_the_reads(tmp_path: Path) -> None:
    assert call_stand_in(tmp_path, [PR1])[:2][0] == 0
    assert '"merge_commit_sha"' in call_stand_in(tmp_path, [PR1])[1]
    assert call_stand_in(tmp_path, [f"repos/{REPO}/labels/release"])[0] == 1  # "no such label"
    assert call_stand_in(tmp_path, [f"repos/{REPO}/releases/tags/v6.0.0"])[0] == 1


INJECTED = [
    'gh api "repos/$REPO/pulls/1" -f title=x || true',
    'gh api "repos/$REPO/pulls/1" -F prerelease=true || true',
    'gh api "repos/$REPO/pulls/1" --method PATCH || true',
    'gh api "repos/$REPO/pulls/1" --input /dev/null || true',
    'gh api "repos/$REPO/pulls/1" --raw-field=title=x || true',
    'curl -s "https://api.github.com/repos/$REPO/pulls/1" || true',
    "git push origin HEAD || true",
]


@pytest.mark.parametrize("line", INJECTED)
def test_a_write_that_skips_the_practice_guard_is_caught(tmp_path: Path, line: str) -> None:
    """The negative control: a copy of the script with one call that bypasses `run()` (no -X)."""
    text = SCRIPT.read_text(encoding="utf-8")
    anchor = "fail=0\n"
    assert text.count(anchor) == 1
    broken = tmp_path / "backfill.sh"
    broken.write_text(text.replace(anchor, f"{anchor}{line}\n"), encoding="utf-8")

    run = practice(tmp_path, script=broken)

    assert not_reads(run), "the injected write went unnoticed"
    assert any(c.startswith(("WRITE ", "OTHER ")) for c in run.calls)


# ---- a row of the map is checked before it is used (security review L3) -------------------------
def first_rows(n: int) -> list[str]:
    lines = MAP.read_text(encoding="utf-8").splitlines()
    return [ln for ln in lines if ln and not ln.startswith("#")][:n]


@pytest.mark.parametrize(
    ("column", "value"),
    [
        (5, "@/etc/passwd"),
        (5, "yes"),
        (0, "1/../../x"),
        (1, "v1.0.0/../x"),
        (1, "1.0.0"),
        (3, "XIII;id"),  # security review L4: the Mark and the kind are checked too
        (3, "x-ray"),
        (3, "XII--XIII"),
        (4, "feature"),
        (4, "docs;x"),
    ],
    ids=[
        "pre-file",
        "pre-word",
        "num-path",
        "ver-path",
        "ver-no-v",
        "mark-semicolon",
        "mark-word",
        "mark-empty-part",
        "kind-unknown",
        "kind-semicolon",
    ],
)
def test_a_malformed_row_is_reported_and_never_used(
    tmp_path: Path, column: int, value: str
) -> None:
    good, bad = (Row(*ln.split("\t")) for ln in first_rows(2))
    cells = list(vars(bad).values())
    cells[column] = value
    tsv = tmp_path / "map.tsv"
    tsv.write_text("\t".join(vars(good).values()) + "\n" + "\t".join(cells) + "\n", "utf-8")

    run = practice(tmp_path, env={"MAP": str(tsv)})

    assert run.code == 1 and "malformed row, skipped" in run.err
    assert value not in "\n".join(run.out + run.calls)  # never reached gh, never printed as DRY
    assert not any(f"/pulls/{bad.num}" in c for c in run.calls)
    assert [ln for ln in run.out if ln.startswith("PR #")] == [f"PR #{good.num} → {good.title}"]


# ---- the target repository is named, and --apply needs it confirmed (security review L4) ---------
def test_the_first_line_names_the_repository_and_the_mode(tmp_path: Path) -> None:
    run = practice(tmp_path)
    assert run.out[0] == (
        f"Practice run for {REPO} from docs/github-backfill.tsv "
        "(nothing changes; --apply makes the changes)"
    )


def test_a_mistyped_apply_is_still_a_practice_run(tmp_path: Path) -> None:
    run = practice(tmp_path, "--aply")
    assert run.code == 0 and run.out[0].startswith("Practice run for ")
    assert not_reads(run) == []


@pytest.mark.parametrize("confirm", [(), ("Shark2558/jarvis-web",), ("someone/other",)])
def test_apply_refuses_a_repository_from_the_environment_unless_confirmed(
    tmp_path: Path, confirm: tuple[str, ...]
) -> None:
    run = practice(tmp_path, "--apply", *confirm, env={"REPO": "someone/else"})

    assert run.code == 2 and run.calls == []  # refused before any call at all
    assert "REPO is someone/else" in run.err and "--apply someone/else" in run.err


# ---- --apply where GitHub refuses every write (code review M3) ----------------------------------
BY_HAND = "by hand on the GitHub website"


def test_every_refused_write_is_reported_once_and_the_run_goes_on_to_the_end(
    tmp_path: Path,
) -> None:
    """Under `set -e` a refused label, retitle or label write once ended the run with only gh's
    own error. Now each one is reported with what to do by hand, never tried twice (a Mark label
    named on several rows is asked for once), every row is still worked through, and the run
    exits 1. The stand-in refuses every write (exit 5), so nothing can reach GitHub."""
    run = practice(tmp_path, "--apply")

    assert run.code == 1, run.err
    assert run.out[0] == f"Applying to {REPO} from docs/github-backfill.tsv"
    assert not any(ln.startswith("DRY:") for ln in run.out)
    assert [ln for ln in run.out if ln.startswith("PR #")] == [
        f"PR #{r.num} → {r.title}" for r in rows()
    ]
    assert [c for c in run.calls if c.startswith(("ODD ", "OTHER "))] == []
    writes = [c for c in run.calls if c.startswith("WRITE ")]
    assert len(writes) == len(set(writes))  # each refused write tried once, never again
    marks = sorted({m for r in rows() for m in r.mark.split("-")})
    label_posts = [w for w in writes if w.startswith(f"WRITE -X POST repos/{REPO}/labels ")]
    assert len(label_posts) == 3 + len(marks)  # release, hotfix, docs and each Mark, once
    assert len(writes) == len(label_posts) + 3 * len(rows())  # title, labels, release per PR
    reports = [ln for ln in run.err.splitlines() if BY_HAND in ln]
    assert len(reports) == len(writes)
    for m in marks:
        assert (
            f'Label "Mark {m}": GitHub refused it; create it {BY_HAND} (colour #0C2D66)' in reports
        )
    for r in rows():
        sha = f"{int(r.num):040d}"
        mine = [ln for ln in reports if ln.startswith(f"PR #{r.num}: ")]
        assert mine == [
            f"PR #{r.num}: GitHub refused the title and header line; set them {BY_HAND} "
            f"(title: {r.title})",
            f"PR #{r.num}: GitHub refused the labels; add them {BY_HAND}: "
            + ", ".join([r.kind, *(f"Mark {m}" for m in r.mark.split("-"))]),
            f"PR #{r.num}: GitHub refused the release {r.version}; create it {BY_HAND} "
            f"(tag {r.version} on {sha})",
        ], mine


def test_a_refused_retitle_of_a_headed_pull_request_names_the_title_only(tmp_path: Path) -> None:
    run = practice(tmp_path, "--apply", headed="27")

    assert run.code == 1
    want = (
        f"PR #27: GitHub refused the title; set it {BY_HAND}: v6.0.0 · R6 The Build Book · Mark XII"
    )
    assert want in run.err.splitlines()
