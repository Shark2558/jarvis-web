# evals/run_all_mock.py
"""Run every eval suite against the mock provider (CI plumbing + safety gates).

    python evals/run_all_mock.py

Equivalent to `make eval-mock` once the Makefile points here: phase0 (core loop plumbing),
slice6 (calendar correctness over a fixture + the injection suite, whose gates are hard) and the
slice 7 morning brief (due-logic, composed facts, AI-line injection containment + its negative
control) and slice 7b's monthly limit (rupees only; no paid call at or over the limit, on every
path; + its negative control) and slice 8's long-term memory (recall, poisoning, training-brain
gate, sensitive data, contradictions, round trip, budget; + negative controls) and slice 9's
voice (speakable text, persona per wit level, voice billing past the free allowance + its
negative control, provider error mapping, transcribe input validation) and slice 10 B's web search
(citations, injection pages, the private-query guard; + two negative controls) and slice 10 C's
to-do list (Google Tasks tools: correctness, the optional scope, injection in task notes → 0
deletes without approval; + its negative control) and slice 10 D's permissions (policy matrix,
deny path, passkey ceremonies with a software authenticator; + its negative control) and slice
10 E's attached documents (extraction limits, recall via doc_search from a 100-page PDF,
injection inside a document + its negative control, training-brain privacy) and slice 11 B's
reminders (plan evals 5 and 6: tagged pop-up events, alerts before a meeting; + its negative
control) and slice 11 A's undo-able deletes (plan evals 1, 2, 3, 4, 7, 9: own items deleted with
Undo, shared ones R3, a mail can't delete, the 10-delete cap, restore, fail-closed snapshots; +
negative controls), slice 11 C's approvals (plan eval 8, Approve all: 3 R2 run, R3 stays;
drafts to un-typed addresses ask; + negative controls) and slice 11 D8's provenance-based trust
(the owner's own items don't taint; an invite, a Gmail to-do or a mail still does; + negative
controls) and slice 12 D1's Drive (chosen folders only: 25 path cases, 10 hostile files; + the
parents-check-off and trusted-tools negative controls) and slice 12's Maps and YouTube (Google's
free-allowance ledger, per-message caps, Home / Work, attribution and links on every card, fenced
titles, the owner's playlist grant; + the ledger-off negative control) and slice 12 C's contacts
look-ups and WhatsApp drafts (17 cases: matches, +91, the optional Grant, drafts by number or
name, the warning for a number read from an email, the 2,000 character limit, Never on both rows,
Unicode kept and the link built exactly; nothing is ever sent; + its negative control), R1's
telegram, activity, offline, packages, groceries, family and mail-aloud suites, and R2's vault,
DigiLocker import, things, notes, privacy dashboard and the cross-cutting r2_needles scan (a full
ID number, file bytes, a place and a note never reach a document (a waiting approval card aside,
plan D13), log, audit entry, Activity row, alert, training brain or a Telegram turn with the
switch off), and R3's home link, burglar alarm, faces and alert-policy suites with the r3_needles
scan through the wired app (a snapshot, the Home Assistant token, the link seed and a child's name
never reach a document, log or audit entry; the snapshot only Telegram's photo, with the opt-in;
the child's name no alert), and R4's r4_needles scan (a red vitals line and a self-health fault
both ring in quiet hours; no-AI mode answers vitals / systems / calendar with no model call and
refuses drafting; a bare private name is refused with no links; a pasted key never reaches a
document, log, audit entry, card or Telegram text; a child is never named; + three negative
controls), and R6's build book (gen, seal, access, guest, wipe, lock: each part with a control that
must fail it). The exit status is the gated suites: phase0 --mock is a smoke run and never fails CI.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).parent
SUITES = [
    ("phase0 (smoke)", [sys.executable, str(HERE / "phase0" / "run.py"), "--mock"], False),
    ("slice6 (gated)", [sys.executable, str(HERE / "slice6" / "run.py"), "--mock"], True),
    ("brief (gated)", [sys.executable, str(HERE / "brief" / "run.py"), "--mock"], True),
    ("budget (gated)", [sys.executable, str(HERE / "budget" / "run.py"), "--mock"], True),
    ("memory (gated)", [sys.executable, str(HERE / "memory" / "run.py"), "--mock"], True),
    ("voice (gated)", [sys.executable, str(HERE / "voice" / "run.py"), "--mock"], True),
    ("web (gated)", [sys.executable, str(HERE / "web" / "run.py"), "--mock"], True),
    ("tasks (gated)", [sys.executable, str(HERE / "tasks" / "run.py"), "--mock"], True),
    ("permissions (gated)", [sys.executable, str(HERE / "permissions" / "run.py"), "--mock"], True),
    ("documents (gated)", [sys.executable, str(HERE / "documents" / "run.py"), "--mock"], True),
    ("reminders (gated)", [sys.executable, str(HERE / "reminders" / "run.py"), "--mock"], True),
    ("undo (gated)", [sys.executable, str(HERE / "undo" / "run.py"), "--mock"], True),
    ("approvals (gated)", [sys.executable, str(HERE / "approvals" / "run.py"), "--mock"], True),
    ("trust (gated)", [sys.executable, str(HERE / "trust" / "run.py"), "--mock"], True),
    ("drive (gated)", [sys.executable, str(HERE / "drive" / "run.py"), "--mock"], True),
    ("maps (gated)", [sys.executable, str(HERE / "maps" / "run.py"), "--mock"], True),
    ("youtube (gated)", [sys.executable, str(HERE / "youtube" / "run.py"), "--mock"], True),
    (
        "contacts+whatsapp (gated)",
        [sys.executable, str(HERE / "contacts_whatsapp" / "run.py"), "--mock"],
        True,
    ),
    ("telegram (gated)", [sys.executable, str(HERE / "telegram" / "run.py"), "--mock"], True),
    ("activity (gated)", [sys.executable, str(HERE / "activity" / "run.py"), "--mock"], True),
    ("offline (gated)", [sys.executable, str(HERE / "offline" / "run.py"), "--mock"], True),
    ("packages (gated)", [sys.executable, str(HERE / "packages" / "run.py"), "--mock"], True),
    ("groceries (gated)", [sys.executable, str(HERE / "groceries" / "run.py"), "--mock"], True),
    ("family (gated)", [sys.executable, str(HERE / "family" / "run.py"), "--mock"], True),
    ("mail aloud (gated)", [sys.executable, str(HERE / "mail_aloud" / "run.py"), "--mock"], True),
    # R2: the vault, DigiLocker import, things, notes, the privacy dashboard and the cross-cutting
    # needle scan (each with its negative controls)
    ("vault (gated)", [sys.executable, str(HERE / "vault" / "run.py"), "--mock"], True),
    ("digilocker (gated)", [sys.executable, str(HERE / "digilocker" / "run.py"), "--mock"], True),
    ("belongings (gated)", [sys.executable, str(HERE / "belongings" / "run.py"), "--mock"], True),
    ("notes (gated)", [sys.executable, str(HERE / "notes" / "run.py"), "--mock"], True),
    ("privacy (gated)", [sys.executable, str(HERE / "privacy" / "run.py"), "--mock"], True),
    ("r2 needles (gated)", [sys.executable, str(HERE / "r2_needles" / "run.py"), "--mock"], True),
    # R3: the home link, the burglar alarm, faces with consent, the one alert policy and the
    # cross-cutting needle scan through the wired app (each with its negative controls)
    ("home link (gated)", [sys.executable, str(HERE / "home_link" / "run.py"), "--mock"], True),
    ("home alarm (gated)", [sys.executable, str(HERE / "home_alarm" / "run.py"), "--mock"], True),
    ("faces (gated)", [sys.executable, str(HERE / "faces" / "run.py"), "--mock"], True),
    ("notify (gated)", [sys.executable, str(HERE / "notify" / "run.py"), "--mock"], True),
    ("r3 needles (gated)", [sys.executable, str(HERE / "r3_needles" / "run.py"), "--mock"], True),
    # R4 I1: the cross-part needle scan through the wired app (a red vitals line and a health fault
    # both ring in quiet hours; no-AI mode answers the free skills and refuses drafting; a bare
    # private name gets no links; a pasted key never appears anywhere; a child is never named)
    ("r4 needles (gated)", [sys.executable, str(HERE / "r4_needles" / "run.py"), "--mock"], True),
    # R6 I1: the build book -- the generator's determinism and scrub, sealing and retention, the
    # passkey + fresh sign-in access, the guest lane against a worst-case model, the wipe's needle
    # scan and the guest lock; each part's negative control must make the suite fail
    ("r6_book (gated)", [sys.executable, str(HERE / "r6_book" / "run.py"), "--mock"], True),
    # R11 I1: the free proactive helpers -- I0's gate, the four parts (bills and the UPI payment,
    # home and outside, nudges, the kitchen) and the cross-part needle scan after a whole day;
    # each built part's negative control must make the suite fail
    ("r11_helpers (gated)", [sys.executable, str(HERE / "r11_helpers" / "run.py"), "--mock"], True),
]


def main() -> int:
    failed: list[str] = []
    for name, cmd, gated in SUITES:
        print(f"\n===== {name} =====", flush=True)
        rc = subprocess.run(cmd, check=False).returncode
        if gated and rc != 0:
            failed.append(name)
    print("\nALL MOCK EVALS:", "PASS" if not failed else f"FAIL ({', '.join(failed)})")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
