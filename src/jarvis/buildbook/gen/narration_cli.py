# src/jarvis/buildbook/gen/narration_cli.py
"""R6.4 D6 (docs/plans/r6-4-book-look.md): the narration writers' tools, inside
`python -m jarvis.buildbook.gen pages ...` (`gen/pages_cli.py` parses the flags):

    --narration-list            every chapter: id, kind, title, pages, status, minutes; the counts
    --narration-pack ID         what a writer needs for one chapter: each page in order with its
                                five sections as written, its flowchart's boxes and connectors (the
                                cue targets) and the facts the pages use, with their values
    --narration-check [ID ...]  every problem of the scripts named (all chapters when none, and
                                any script for no chapter), one line each: `<id>: <problem>`;
                                `--allow-missing` lets a chapter with no script yet pass
    --narration-stamp ID ...    writes only the `pages` block of each script from its pages now;
                                refuses (exit 1) a script with any problem but staleness

`pages --check` (no ids) runs `check_all` too, so CI's strict check covers the narration. The
output names chapter and page ids, fact keys, box ids and rule words; never a spoken line.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Sequence

from jarvis.buildbook.book import chapters as ch
from jarvis.buildbook.book import narration_check as nc
from jarvis.buildbook.book.authored import BOOK_DIR, Env, judge, write_text
from jarvis.buildbook.book.files import stamped
from jarvis.buildbook.book.narration import NARRATION, all_scripts, script_path
from jarvis.buildbook.gen.runner import say
from jarvis.buildbook.writer import fill
from jarvis.buildbook.writer.model import DRAFT_SECTIONS, HEADINGS

STATUSES = ("ok", "stale", "failing", "missing")
GUIDE_FILE = f"{BOOK_DIR}/AUTHORING-NARRATION.md"
NOT_A_CHAPTER = "not a chapter of the book"


def plans(env: Env) -> tuple[ch.ChapterPlan, ...]:
    return ch.chapters(env.facts.pages)


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" + ("" if n == 1 else "s")


def totals(n: int, counts: Counter[str], allowed: bool = False) -> str:
    tail = " (allowed)" if allowed and counts["missing"] else ""
    return _plural(n, "narration") + ": " + ", ".join(f"{counts[s]} {s}" for s in STATUSES) + tail


def _minutes(verdict: nc.ScriptVerdict, env: Env) -> int:
    return nc.minutes_of(fill.fill(t.text, env.facts) for t in verdict.told)


# ---- --narration-list ---------------------------------------------------------------------------
def list_all(env: Env) -> int:
    root, counts, found = env.repo.root, Counter[str](), plans(env)
    for plan in found:
        verdict = nc.judge_script(root, plan, env)
        counts[verdict.status] += 1
        pages = _plural(len(plan.pages), "page")
        say(f"{plan.id}\t{plan.kind}\t{plan.title}\t{pages}\t{verdict.status}\t"
            f"{_minutes(verdict, env)} min")  # fmt: skip
    say(_plural(len(found), "chapter") + ": " + ", ".join(f"{counts[s]} {s}" for s in STATUSES))
    return 0


# ---- --narration-check --------------------------------------------------------------------------
def strays(env: Env, known: Iterable[str]) -> list[str]:
    """Scripts for no chapter, and files of `narration/` that aren't scripts at all."""
    found, ids = all_scripts(env.repo.root), set(known)
    out = [e for name, e in sorted(found.errors.items())
           if name.removeprefix(f"{NARRATION}/").removesuffix(".md") not in ids]  # fmt: skip
    return out + [f"{NARRATION}/{cid}.md: {NOT_A_CHAPTER}" for cid in sorted(found.items)
                  if cid not in ids]  # fmt: skip


def check_all(
    env: Env, ids: Sequence[str] = (), *, allow_missing: bool
) -> tuple[list[str], Counter[str], int]:
    """(problem lines, counts by status, chapters checked) for the scripts named (all when
    none, with the strays)."""
    found = {p.id: p for p in plans(env)}
    lines, counts = [], Counter[str]()
    for cid in ids or list(found):
        plan = found.get(cid)
        if plan is None:
            lines.append(f"{cid}: {NOT_A_CHAPTER}")
            continue
        verdict = nc.judge_script(env.repo.root, plan, env)
        counts[verdict.status] += 1
        if verdict.status == "missing" and allow_missing:
            continue
        lines += [f"{cid}: {p}" for p in verdict.problems]
    lines += [] if ids else strays(env, found)
    return lines, counts, sum(counts.values())


def check(env: Env, ids: Sequence[str], *, allow_missing: bool) -> int:
    lines, counts, n = check_all(env, ids, allow_missing=allow_missing)
    for line in lines:
        say(line)
    say(f"checked {totals(n, counts, allow_missing)}; {len(lines)} problems")
    return 1 if lines else 0


# ---- --narration-stamp --------------------------------------------------------------------------
def _stamp_one(env: Env, plan: ch.ChapterPlan) -> list[str]:
    verdict = nc.judge_script(env.repo.root, plan, env)
    if verdict.script is None:
        return list(verdict.problems)
    blocking = [p for p in verdict.problems if not p.startswith(nc.STALE)]
    if blocking:
        return blocking
    hashes = nc.stamps(env.repo.root, plan)
    path = script_path(env.repo.root, plan.id)
    write_text(path, stamped(path.read_text(encoding="utf-8"), hashes, "pages"))
    if nc.judge_script(env.repo.root, plan, env).status != "ok":
        return ["the stamp didn't read back (the pages block)"]
    return []


def stamp(env: Env, ids: Iterable[str]) -> int:
    found, refused = {p.id: p for p in plans(env)}, 0
    for cid in ids:
        plan = found.get(cid)
        why = [NOT_A_CHAPTER] if plan is None else _stamp_one(env, plan)
        for reason in why:
            say(f"{cid}: not stamped: {reason}")
        refused += bool(why)
        if not why and plan is not None:
            say(f"{cid}: stamped ({_plural(len(plan.pages), 'page')})")
    return 1 if refused else 0


# ---- --narration-pack ---------------------------------------------------------------------------
def _flow_lines(env: Env, page_id: str) -> list[str]:
    flow = nc.flow_of(env.repo.root, page_id)
    if flow is None:
        return ["  flowchart: none (use [show:...] cues)"]
    out = [f"  flowchart: {flow.title} ([show:overview], [node:<id>], [edge:<from>><to>])"]
    out += [f"  box {n.id}: {n.label} ({n.kind})" for n in flow.nodes]
    out += [f"  connector {e.from_}>{e.to}" + (f": {e.label}" if e.label else "") + f" ({e.style})"
            for e in flow.edges]  # fmt: skip
    return out


def _page_lines(env: Env, page_id: str, n: int, of: int) -> tuple[list[str], set[str]]:
    ip = env.facts.page(page_id)
    title, kind = (ip.title, ip.kind) if ip is not None else (page_id, "?")
    verdict = judge(env.repo.root, ip, env) if ip is not None else None
    out = [f"page {n} of {of}: {page_id} - {title} ({kind})",
           f"  status: {verdict.status if verdict else 'not an indexed page'}"]  # fmt: skip
    keys: set[str] = set()
    page = verdict.page if verdict else None
    for sid in DRAFT_SECTIONS:
        text = page.sections.get(sid, "") if page else ""
        keys.update(fill.keys_in(text))
        out.append(f"  {HEADINGS[sid]}: {' '.join(env.scrub.clean(text).split())}")
    return out + _flow_lines(env, page_id), keys


def pack(env: Env, cid: str) -> int:
    plan = ch.find(plans(env), cid)
    if plan is None:
        say(f"{cid}: {NOT_A_CHAPTER}")
        return 1
    verdict = nc.judge_script(env.repo.root, plan, env)
    head = [
        f"chapter: {plan.id} - {plan.title} ({plan.kind}, {_plural(len(plan.pages), 'page')})",
        f"status: {verdict.status}",
        f"write: {BOOK_DIR}/{NARRATION}/{plan.id}.md",
        f"rules: {GUIDE_FILE} (a line at most 240 characters once filled; about 4 to 14 minutes)",
    ]
    body, keys = [], set()
    for n, pid in enumerate(plan.pages, start=1):
        lines, used = _page_lines(env, pid, n, len(plan.pages))
        body += lines
        keys |= used
    facts = []
    for key in sorted(k for k in keys if k in env.facts.values):
        v = env.facts.values[key]
        flag = "verified" if v.verified else 'Unverified: say "Unverified" in its line'
        facts.append(f"  {key} = {fill.show(v.value)}  [{flag}]")
    tail = ["facts the pages use (write {{fact:<key>}}; any key of the pack is allowed):", *facts]
    for line in (*head, *body, *tail):
        say(line)
    return 0


__all__ = ["GUIDE_FILE", "check", "check_all", "list_all", "pack", "plans", "stamp", "totals"]
