# src/jarvis/buildbook/gen/pages_cli.py
"""R6.3.1 D5, D6 (docs/plans/r6-3-1-book-at-build.md): the Workshop's tools for writing the full
book's pages, `python -m jarvis.buildbook.gen pages ...` (one of these four):

    --list              every indexed page: id, kind, title, status (missing | stale | failing |
                        ok), tab-separated, one a line; then the counts by kind and by status
    --pack ID           what a writer needs for one page: its title, kind, refs and files, what
                        it may cite, every fact of its slice with its value and whether it is
                        verified, its card, and the generator's plain text
    --check [ID ...]    every problem of the pages named (all of them when none, and any page or
                        flowchart file for no indexed page), one line each: `<id>: <problem>`;
                        a page not written yet is `<id>: missing`; exit 1 on any problem
    --stamp ID ...      rewrites only the `sources` block of each page from its refs' tracked
                        files now; refuses (exit 1) a page with any problem but staleness

R6.4 D6 (docs/plans/r6-4-book-look.md): the chapters' narration scripts, `gen/narration_cli.py`:
--narration-list, --narration-pack ID, --narration-check [ID ...], --narration-stamp ID ...; and
`--check` with no ids checks every narration script too (`--allow-missing` covers both).

    --repo DIR          the checkout (default: the git checkout around the working folder)
    --allow-missing     with --check: a page not written yet is no problem (a writer checks
                        only the pages written so far)

The fact pack comes from `build/book-cache/` (`gen/facts_cache.py`): built once per tree (about
half a minute), then a check takes seconds. JARVIS_OWNER_EMAILS (comma-separated; never printed)
adds the owner-address check when set. The output names ids, paths, fact keys and rule words,
never a personal finding's text.
"""

from __future__ import annotations

import argparse
from collections import Counter
from collections.abc import Iterable, Sequence
from pathlib import Path

from jarvis.buildbook.book import authored
from jarvis.buildbook.book.authored import STALE, Env, judge
from jarvis.buildbook.book.flow import REQUIRED_FOR
from jarvis.buildbook.facts_model import IndexedPage
from jarvis.buildbook.gen import facts_cache, narration_cli
from jarvis.buildbook.gen.repo import GenError, Repo
from jarvis.buildbook.gen.runner import say
from jarvis.buildbook.gen.scrub import default_scrubber
from jarvis.buildbook.gen.write import EMAILS_ENV, owner_emails  # one rule (R6.3.1 E)
from jarvis.buildbook.writer import fill, packs, pages
from jarvis.buildbook.writer.model import DRAFT_SECTIONS, SECTION_CAPS

PROG = "python -m jarvis.buildbook.gen pages"
KINDS = ("chapter", "module", "card", "screen", "service")
STATUSES = ("ok", "stale", "failing", "missing")
GUIDE_FILE = f"{authored.BOOK_DIR}/AUTHORING.md"
BUILDING = "pages: building the fact pack for this tree (about half a minute, once per tree)"


def _args(argv: Sequence[str] | None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(prog=PROG, description=(__doc__ or "").split("\n\n")[0])
    ap.add_argument("--repo", type=Path, default=None)
    act = ap.add_mutually_exclusive_group(required=True)
    act.add_argument("--list", action="store_true")
    act.add_argument("--pack", metavar="ID")
    act.add_argument("--check", nargs="*", metavar="ID")
    act.add_argument("--stamp", nargs="+", metavar="ID")
    act.add_argument("--narration-list", action="store_true")  # R6.4 D6
    act.add_argument("--narration-pack", metavar="ID")
    act.add_argument("--narration-check", nargs="*", metavar="ID")
    act.add_argument("--narration-stamp", nargs="+", metavar="ID")
    ap.add_argument("--allow-missing", action="store_true")
    return ap.parse_args(argv)


def main(argv: Sequence[str] | None = None, *, build: facts_cache.Builder | None = None) -> int:
    args = _args(argv)
    try:
        repo = Repo.from_git(args.repo)
        builder = build or facts_cache.build_pack
        pack, _ = facts_cache.facts_for(repo, builder, note=lambda: say(BUILDING, err=True))
    except GenError as exc:
        say(f"pages: {exc}", err=True)
        return 1
    env = Env(facts=pack, scrub=default_scrubber(), repo=repo, emails=owner_emails())
    if args.list:
        return _list(env)
    if args.pack is not None:
        return _pack(env, args.pack)
    if args.check is not None:
        return _check(env, args.check, allow_missing=args.allow_missing)
    if args.stamp is not None:
        return _stamp(env, args.stamp)
    return _narration(env, args)


def _narration(env: Env, args: argparse.Namespace) -> int:
    """R6.4 D6: the narration flags (`gen/narration_cli.py`)."""
    if args.narration_list:
        return narration_cli.list_all(env)
    if args.narration_pack is not None:
        return narration_cli.pack(env, args.narration_pack)
    if args.narration_check is not None:
        return narration_cli.check(env, args.narration_check, allow_missing=args.allow_missing)
    return narration_cli.stamp(env, args.narration_stamp)


# ---- --list -------------------------------------------------------------------------------------
def _totals(n: int, counts: Counter[str], head: str = "") -> str:
    return head + f"{n} pages: " + ", ".join(f"{counts[s]} {s}" for s in STATUSES)


def _list(env: Env) -> int:
    root, counts, kinds = env.repo.root, Counter[str](), Counter[str]()
    for ip in env.facts.pages:
        verdict = judge(root, ip, env)
        counts[verdict.status] += 1
        kinds[ip.kind] += 1
        say(f"{ip.id}\t{ip.kind}\t{ip.title}\t{verdict.status}")
    say("by kind: " + ", ".join(f"{k} {kinds[k]}" for k in KINDS if kinds[k]))
    say(_totals(len(env.facts.pages), counts))
    return 0


# ---- --check ------------------------------------------------------------------------------------
def _strays(env: Env) -> list[str]:
    """Files under pages/ and flows/ that belong to no indexed page, or are no page's at all."""
    root, indexed = env.repo.root, {ip.id for ip in env.facts.pages}
    found_pages, found_flows = authored.all_pages(root), authored.all_flows(root)
    out = [e for n, e in sorted({**found_pages.errors, **found_flows.errors}.items())
           if Path(n).stem not in indexed]  # fmt: skip
    for folder, ids, suffix in (("pages", found_pages.items, ".md"),
                                ("flows", found_flows.items, ".json")):  # fmt: skip
        out += [f"{p}: not an indexed page ({folder}/{p}{suffix})" for p in sorted(ids)
                if p not in indexed]  # fmt: skip
    return out


def _check(env: Env, ids: Sequence[str], *, allow_missing: bool) -> int:
    indexed = {ip.id: ip for ip in env.facts.pages}
    counts, problems = Counter[str](), 0
    for pid in ids or list(indexed):
        ip = indexed.get(pid)
        if ip is None:
            say(f"{pid}: not an indexed page")
            problems += 1
            continue
        verdict = judge(env.repo.root, ip, env)
        counts[verdict.status] += 1
        if verdict.status == "missing" and allow_missing:
            continue
        for problem in verdict.problems:
            say(f"{pid}: {problem}")
            problems += 1
    for stray in [] if ids else _strays(env):
        say(stray)
        problems += 1
    checked = sum(counts.values())
    tail = " (allowed)" if allow_missing and counts["missing"] else ""
    told = ""
    if not ids:  # R6.4 D6: the strict check covers every chapter's narration script too
        lines, by_status, n = narration_cli.check_all(env, allow_missing=allow_missing)
        for line in lines:
            say(line)
        problems += len(lines)
        told = "; " + narration_cli.totals(n, by_status, allow_missing)
    say(_totals(checked, counts, head="checked ") + tail + told + f"; {problems} problems")
    return 1 if problems else 0


# ---- --stamp ------------------------------------------------------------------------------------
def _stamp_one(env: Env, ip: IndexedPage) -> list[str]:
    """Why the page can't be stamped ([] once its `sources` are written)."""
    verdict = judge(env.repo.root, ip, env)
    if verdict.page is None:
        return list(verdict.problems)
    blocking = [p for p in verdict.problems if not p.startswith(STALE)]
    if blocking:
        return blocking
    hashes = authored.source_hashes(env.repo, ip.refs)
    if set(hashes) != set(ip.refs):
        return ["a ref has no tracked file to hash"]
    path = authored.page_path(env.repo.root, ip.id)
    authored.write_text(path, authored.stamped(path.read_text(encoding="utf-8"), hashes))
    if authored.load_page(path).sources != hashes:
        return ["the stamp didn't read back (the sources block)"]
    return []


def _stamp(env: Env, ids: Iterable[str]) -> int:
    indexed, refused = {ip.id: ip for ip in env.facts.pages}, 0
    for pid in ids:
        ip = indexed.get(pid)
        why = ["not an indexed page"] if ip is None else _stamp_one(env, ip)
        for reason in why:
            say(f"{pid}: not stamped: {reason}")
        if why:
            refused += 1
        elif ip is not None:
            n = len(ip.refs)
            say(f"{pid}: stamped ({n} source{'' if n == 1 else 's'})")
    return 1 if refused else 0


# ---- --pack -------------------------------------------------------------------------------------
def _facts(ip: IndexedPage, env: Env, cited: list[str]) -> list[str]:
    keys = [line.split(" = ", 1)[0] for line in packs.fact_lines(ip, env.facts, cited)]
    out = []
    for k in keys:
        v = env.facts.values[k]
        flag = "verified" if v.verified else 'Unverified: say "Unverified" in its sentence'
        out.append(f"  {k} = {fill.show(v.value)}  [{flag}]")
    return out


def _generator_text(ip: IndexedPage, env: Env) -> list[str]:
    page = pages.generator_page(ip, env.facts)
    return [f"  {s.heading}: {s.text}" for s in page.sections if s.text.strip()]


def _card_text(ip: IndexedPage, env: Env) -> list[str]:
    guide = env.repo.text(packs.GUIDE) or ""
    found = packs.cards(guide, [s for s in ip.sources if s.startswith("C")])
    return [f"  {line}" for text in found.values() for line in env.scrub.clean(text).splitlines()]


def brief(ip: IndexedPage, env: Env) -> list[str]:
    """The lines `--pack` prints for one page."""
    root = env.repo.root
    cited = [env.repo.text(f) or "" for r in ip.refs for f in authored.files_of(env.repo, r)]
    need = "required" if ip.kind in REQUIRED_FOR else "optional"
    caps = "/".join(f"{SECTION_CAPS[s]:,}" for s in DRAFT_SECTIONS)
    return [
        f"page: {ip.id} - {ip.title}",
        f"kind: {ip.kind} - part: {ip.part}" + (f" - module: {ip.chapter}" if ip.chapter else ""),
        f"status: {judge(root, ip, env).status}",
        f"write: {authored.BOOK_DIR}/pages/{ip.id}.md",
        f"flowchart: {need} ({authored.BOOK_DIR}/flows/{ip.id}.json)",
        f"rules: {GUIDE_FILE} (section caps {caps} characters once filled)",
        f"sources: {', '.join(ip.sources) or '(none)'}",
        f"refs ({len(ip.refs)}; read each one, then --check and --stamp):",
        *(f"  {r}" for r in ip.refs),
        "may cite (backticked, exactly as written here):",
        *(f"  {a}" for a in packs.allowed(ip, env.facts, cited)),
        "facts (write {{fact:<key>}}; never type a number outside the made-up example):",
        *_facts(ip, env, cited),
        "card (from the guide):",
        *(_card_text(ip, env) or ["  (none)"]),
        "the generator's text (the reader shows it until this page passes):",
        *_generator_text(ip, env),
    ]


def _pack(env: Env, pid: str) -> int:
    ip = env.facts.page(pid)
    if ip is None:
        say(f"{pid}: not an indexed page")
        return 1
    for line in brief(ip, env):
        say(line)
    return 0


__all__ = ["EMAILS_ENV", "PROG", "brief", "main", "owner_emails"]
