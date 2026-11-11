Version v11.0.1 · 11 Nov 2026, 20:33 IST · Release R11 · Status: Current · Owner: 🛠 Mark XIV

# R11 Part A · Today — integration note (items 1, 7, 10)

Branch `r11-a` (from `r11-i0` @ 0e2aec7). Plan: `docs/plans/r11-free-helpers.md` D7, D8, D9, D16–D20.
No wiring file was edited: Part A plugs in through `helpers/today/part.py` `build(ctx)` and
`api/helpers_today.py` only.

## 1. What was built

| Item | What | Where |
|---|---|---|
| 1 Bills | His bills, sealed with the keyring purpose `bills` (AAD `bills/{uid}/v1`); no keyring → "bills are off", never in clear. No card / account / consumer number in any field, the payee's name, the note or the UPI ID: ONE check, `text.has_number` (13+ digits joined across any run of non-alphanumeric separators, digits of any script, invisible characters dropped first; or 5 digits in a row, 11 in a UPI ID); the last 4 digits at most, only in `last4`. A payee's name is Latin letters, spaces and `. , ' & -` (≤ 40; look-alikes mapped, accents dropped; no digit, `@`, bracket, control or bidi character); a label holds no `@`. A month-end day (29–31) is kept as `Due.day`, so each period is due on min(day, the month's length). | `helpers/today/{text,models,store,bills}.py` |
| 1 Reminders | `bills_due` on the 5-minute clock: `bill_due` at his time (default 09:00) 3, 1 and 0 days before, and once overdue the day after; each claimed in `bills_told` in a transaction before the send, released on `SendResult.retry`; sent only through `ctx.sender`; held at night by the policy. | `helpers/today/jobs.py` |
| 1 Prepared payment | `bill_pay_prepare` (R3): the card is written by code from his saved bill ("Get a UPI payment ready: ₹1,240.00 to “Power Co” (test@okfake), note “Electricity Nov”. You confirm it and enter your PIN in your UPI app. JARVIS never pays."; a bill with no payee is paid in its label's safe name), via the read-only `preview`, so a changed bill re-proposes it. Approved, it leaves a 10-minute grant sealed with the bills, pinning exactly what the card showed (amount, due date, UPI ID, payee name: a later change shows nothing); its result names no link. The Today tab spends the grant once: `upi://pay?pa=…&pn=…&am=…&cu=INR&tn=…` (NPCI parameters; RFC 3986, spaces `%20`, never `+`) and a segno QR (SVG data URI). Neither is stored or logged; showing it leaves one kind-only audit line (`bill_payment` / `shown`, no amount, no UPI ID). Cap ₹1,00,000 (owner decision 12; exactly ₹1,00,000 allowed), checked before any card. | `helpers/today/{upi,qr,tools}.py`, `api/helpers_today.py` |
| 1 Payee | `bill_payee_set` (R3) is the only way a UPI ID is set (the tab's form makes the same R3 card). Refused outright while `content_tainted()` ("Type the UPI ID yourself in the Today tab, Sir…"); in a chat turn the UPI ID must also be in his own message, as a whole word, any case (`taint.owner_text`; else `TYPE_IT_HERE`); both checked in `check` before any card; refused at run when its card came from a tainted round (`ToolContext.outside`). The payee's name is quoted on the card; the `bill_add` card shows it too. `bill_add` has no UPI field at all. `tools.TAINT_REFUSAL` is the eval's switch (it turns off the taint and the typed-here checks). | `helpers/today/tools.py` |
| 7 Birthdays | `people/me/connections?personFields=names,birthdays` (≤ 2 pages of 1,000) through `GoogleConnector` and `ContactsClient.require`; his Contacts row obeyed by `Policy.decide("contacts_birthdays", R1)` — Never or unreadable rows → no request; audited kind-only (agent `helpers`). Month and day only (the year and `text` are never read). One reading a day held in memory; a failure retried after 30 min. Job `birthdays` (off until he switches it on; default 08:30): ONE `birthday` alert naming nobody; names only in `named=`; claims in `birthdays_told` (SHA-256 of him, the resource name and the year). | `helpers/today/{birthdays,jobs}.py` |
| 10 Top priority / pending | `PendingService` over `ctx.pending_all()` (+ A's own once), each source ≤ 3 s, a failing one left out and named; ranked overdue → today → urgency → pin (`weight`) → due date. A's sources: bills (current unpaid due date, overdue or within a week) and Google Tasks due by today (his To-dos row obeyed). Tools `focus_now`, `pending_list` (R1, row `nudges`); a to-do's title is fenced for the model and never in `message`. | `helpers/today/{pending,focus}.py` |
| Tools | `bill_list` R1, `bill_add` R2, `bill_paid` R2, `bill_payee_set` R3, `bill_pay_prepare` R3, `contacts_birthdays` R1, `focus_now` R1, `pending_list` R1. | `tools.py`, `focus.py` |
| No-AI | Anchored phrases, first in `route_no_ai`: "what's my top priority", "what is pending", "show my bills", "I paid the X bill" / "mark X paid", "pay the X bill" / "get the X payment ready", "whose birthday is today". The pay / paid phrases fire only when X is one of his bills (`BillStore.knows`: SHA-256 of each name, noted on every read or change); otherwise ("pay rent" with no rent bill, "I paid for lunch") they fall through. "remind me to pay …" stays a reminder. | `phrases.py`, `store.py` |
| Privacy | `helpers_bills` (passkey delete; bills, choices, sent-reminder hashes; export JSON in ₹) and `helpers_birthdays` (simple; claim hashes only). | `privacy.py` |
| Brief | `TodayBrief`: ≤ 3 fixed lines (bills due today / tomorrow / overdue; birthdays today when on; top priority when it isn't a bill). | `brief.py` |
| Routes | `GET /v1/helpers/today`, `POST /bills`, `POST /bills/{id}/paid`, `DELETE /bills/{id}`, `PUT /prefs`, `POST /bills/{id}/payee` and `/pay` (R3 cards through the gateway in HIS conversation; none → 409), `POST /bills/{id}/payment` (once). Owner-only, `no-store`, I0's change limiter. | `api/helpers_today.py`, `helpers/today/views.py` |
| Console | Today tab: top priority, also pending, bills (Pay / Show payment, Set UPI ID, Paid, Remove; a varies amount asked inline; the waiting R3 card shown inline with Approve / Decline and his passkey when in force), the reminder time, the birthday switch with today's and the week's birthdays. `H.*` builders and existing classes only, `textContent` only, ASCII source. | `static/console-helpers-today.js` |
| Eval | `evals/r11_helpers/today.py`, `BUILT = True`, 10 cases; control `taint_check_off` fails `today:emailed-upi-never-a-payee`. | |
| Tests | `tests/test_r11_a_*.py` (14 files, 236 tests), `tests/r11_fakes_a.py`, `tests/browser/test_r11_a_today.py`. Coverage of `helpers/today` + `api/helpers_today.py`: 94 %. | |

## 2. How to check it

```
/tmp/venv-12/bin/pytest -q -p no:cacheprovider tests/test_r11_a_*.py
PYTHONPATH=src /tmp/venv-12/bin/python evals/r11_helpers/run.py --mock --part today
JARVIS_BROWSER_TESTS=1 PYTHONPATH=src /tmp/venv-c/bin/python -m pytest -q tests/browser/test_r11_a_today.py
```

By hand (dev server with `JARVIS_TOKEN_KEY` set): Helpers → Today → Add a bill (Electricity, 1240,
day 13) → Set UPI ID (`test@okfake`) → Approve → Pay → Approve → the QR and "Open in UPI app" show
once; a second Show payment says "Nothing approved to show". With the AI off, "pay the electricity
bill" in the chat makes the same card.

## 3. Needs I1 (wiring files Part A did not touch)

**3.1 `tests/test_r11_wiring.py`** — three I0 assertions say Part A is still a stub. Verified on a
scratch copy (12 passed with Part A built):

```diff
@@ test_the_helpers_start_with_four_empty_parts_and_both_composites
-        assert {p.ready for p in st.r11_parts.values()} == {"not built yet"}
+        assert st.r11_parts["today"].ready.startswith(("Bills,", "Birthdays and"))
         assert st.helpers_sender is not None and st.helpers_off is None
-        assert isinstance(st.helpers_clock, Composite) and st.helpers_clock.job_names == ()
+        assert isinstance(st.helpers_clock, Composite)
+        assert {"bills_due", "birthdays"} <= set(st.helpers_clock.job_names)
@@ test_the_four_part_routers_are_stubs_under_their_own_prefix
-        assert module.PREFIX == f"/v1/helpers/{part}" and module.router.routes == []
+        assert module.PREFIX == f"/v1/helpers/{part}"
+        assert all(r.path.startswith(module.PREFIX) for r in module.router.routes)
@@ test_a_parts_phrase_answers_in_no_ai_mode_through_its_tool
-        assert a.state.brain_mode.phrases == (phrase,)
+        assert phrase in a.state.brain_mode.phrases
```

(With B, C and D merged, the first assertion's other parts change too.)

**3.2 "Approvals waiting" as a pending source (D9).** `HelperContext` has no gateway (wire_r11
runs before it), so Part A could not add it. `pending_all()` is read late, so I1 can add one
source in `api/r11_wiring.py`:

```diff
+class _ApprovalsPending:
+    """D9: the owner's waiting approval cards, as one pending line (read when asked)."""
+
+    name = "approvals"
+
+    def __init__(self, st: Any) -> None:
+        self._st = st
+
+    async def pending(self, uid: str, now: datetime) -> list[PendingItem]:
+        gw = getattr(self._st, "gateway", None)
+        mine = [a for a in await gw.pending() if (a.scope or "").startswith(f"{uid}:")] if gw else []
+        n = len(mine)
+        label = f"{n} approval{'s' if n != 1 else ''} waiting for your OK"
+        return [PendingItem("approvals", label, "today")] if n else []
@@ def _context(...)
+    approvals = _ApprovalsPending(st)
     def pending_all() -> tuple[PendingSource, ...]:
         parts: dict[str, HelperPart] = getattr(st, "r11_parts", None) or {}
-        return tuple(src for p in parts.values() for src in p.pending)
+        return (*(src for p in parts.values() for src in p.pending), approvals)
```

(and `from jarvis.helpers.ports import PendingItem`). Part A's `focus.SOURCE_WORDS` already names
"approvals" and "calendar". The "next calendar event" source of D9 is not built (left for I1 or R12).

**3.3 The payment under the chat reply too (D7 "shown once in the card and the bill row").** The
bill row shows it now; the chat says "open Helpers → Today". A reply card needs a new kind in
`tools/reply_cards.py` (not Part A's file) and a renderer:

```diff
+class UpiCard(_Strict):
+    kind: Literal["upi"] = "upi"
+    link: str = Field(max_length=1100, pattern=r"^upi://pay\?[A-Za-z0-9%@._~=&-]{1,1000}$")
+    qr: str = Field(max_length=20_000, pattern=r"^data:image/svg\+xml;charset=utf-8,")
+    words: str = Field(max_length=TEXT_LIMIT)
-AnyCard = PlacesCard | RouteCard | VideosCard | WhatsAppCard
+AnyCard = PlacesCard | RouteCard | VideosCard | WhatsAppCard | UpiCard
```

then, in `helpers/today/tools.py` `_prepare_tool.run`, after `make_ready`: `if showing_cards(): shown =
await t.service.payment(uid, bill.id)` (spends the grant) and `add_card(UpiCard(link=…, qr=…,
words=…))`; the console draws it like `paymentBox` in `console-helpers-today.js`. Cards are not
stored with the conversation, so "never stored" still holds.

**3.4 `console-helpers.css`** — two rules would let the tab drop its three inline layout styles
(`style.marginTop`, `style.flexWrap`, `style.padding`; no colour, font, radius or shadow):

```diff
+.hp-acts .btn.bact{margin-top:0}
+.hp-acts.hp-wrap{flex-wrap:wrap;padding:0 0 10px}
```

**3.5 Telegram (`tests/test_telegram_tool_guard.py`, `telegram/rules.py`).** That test builds the
gateway without `r11=`, so it passes today. When it gains the R11 tools: `focus_now` and
`pending_list` → `TELEGRAM_SAFE` (his own lists, like `tasks_list`; to-do titles are fenced);
`contacts_birthdays` is already private (`contacts_*`); `bill_list` (amounts and UPI IDs on a cloud
chat) → recommended `PRIVATE_PATTERNS` (`"bill_list"`). R3 cards already wait in the console.

**3.6 Optional.** `console.js` does not refresh the Approvals list when a card is made outside a
chat reply; the Today tab shows its own waiting card, so nothing depends on it. The payment cap is
the constant `models.PAY_CAP_PAISE`; a `bill_pay_cap_inr` setting would be a `config.py` change.
Persona p11.0 `HELPERS_RULE` (D22) is I1's.

## 4. Owner checks

1. **A real UPI app** (unverified from the sandbox): on his phone, prepare a ₹1 payment to his own
   UPI ID and open it in GPay, PhonePe and Paytm: does each accept a pre-filled P2P intent, and does
   the QR scan? If one refuses, the card still shows the UPI ID and amount to type by hand.
2. **Contacts**: Integrations → Grant Contacts, then Helpers → Today → Birthday reminders On. The
   alert names nobody unless Alerts → "names in alerts" is on (owner decision 8, default off).
   Google's page size (1,000) is unverified; two pages are read.
3. **Times**: bills at 09:00, birthdays at 08:30 (changeable in the tab); a bill reminder set for
   23:30 is held for the morning summary.
4. **Approve with the passkey** from the Today tab once, to see the passkey prompt in the console.
5. `JARVIS_TOKEN_KEY` must be set (it is in the cloud deploy); without it the tab says bills are off.

## 5. Review fixes (v11.0.1)

From `review-r11-a-security` and `review-r11-a-code` (branch @ 4813156). Each fix was test-first.

| Finding | Status | Where, and the tests |
|---|---|---|
| Sec HIGH-1 card numbers with other separators | Fixed | `text.has_number`, used by every field, the payee, the note, the UPI ID and `upi_link`; `test_r11_a_numbers.py` (the reviewer's probes, Amex 4-6-5, NBSP, en dash, fullwidth, Arabic-Indic, zero-width) |
| Sec MEDIUM-1 payee unquoted, hidden on `bill_add` | Fixed | quoted on the pay and payee cards, shown on the `bill_add` card; `text.payee_name` safe set; labels refuse `@` |
| Sec MEDIUM-2 UPI ID not from his message | Fixed | `tools.typed_here` in `_check_payee` (chat turns only; the tab's form has no message) |
| Sec LOW-1 to-do title in the brief | Fixed | one quoted line, ≤ 60, no control or bidi character, named "(Google Tasks)" |
| Sec LOW-2 bill labels to the model | Fixed | `bill_for_model` and `focus` fence labels and payees; messages quote them |
| Sec LOW-3 non-ASCII digits as amounts | Fixed | `[0-9]` only in amounts, times and `last4` |
| Sec LOW-4 showing a payment not audited | Fixed | one kind-only line; the Contacts reads outside the gateway: left (below) |
| Code H1 month-end bills | Fixed | `Due.day` (derived from `start` in an older document); `test_r11_a_due.py` |
| Code M1 missing tests | Fixed | exact ₹1,00,000, a bill with no payee through prepare and payment, Tasks not granted / not linked |
| Code M2 pay / paid take any name | Fixed | `phrases_for(store.knows)` |
| Code M3 birthday sweep unguarded | Fixed | `jobs.DailySweep` for both jobs: class name logged, retried on the next run |
| Code L1 to-do title in the brief | Fixed | as Sec LOW-1 |
| Code L2 "₹₹1,240" on the `bill_add` card | Fixed | the amount is parsed, then shown as `inr_short` |
| Code L3 `_denied` grows a day at a time | Fixed | only today's entries are kept |

Left, and why:

- **The birthdays job and the brief read Contacts outside the gateway** (Sec LOW-4, second half).
  The reader obeys his Contacts row (`Policy.decide`, fail closed) and audits a kind-only line, as
  the reviewer found equivalent. Moving it through the gateway needs a gateway in `HelperContext`,
  which is I0's (`helpers/ports.py`, `api/r11_wiring.py`); not proposed for R11.
- **The bill-name memory is per process.** After a restart, "pay the X bill" with the AI off falls
  through until the bills are first read (the `bills_due` job reads every owner's bills on the
  next 5-minute run; the Today tab and every bill tool read them too). With several instances,
  each learns on its own reads. The router has no owner (`NoAIRouter` is `(text, now)`), so it
  asks across the configured owners; the tool then reads only his own bills.
- **Stricter checks apply when a stored bill is read.** A bill saved before v11.0.1 whose payee or
  label fails the new checks would make the book unreadable. R11 has not shipped, so no stored
  document predates them; a dev store from earlier hand checks should be cleared (the privacy
  row `helpers_bills`, passkey delete) before testing again.
- **A payee's name is Latin letters only.** A name in another script is refused ("Latin letters,
  spaces and . , ' & - only"); the confusables table maps the common Cyrillic and Greek look-alikes,
  not all of Unicode's. A label with 13+ digits split by symbols (say, two full dates and an
  amount) is refused as card-like: the false positive is the safe side.

## Change log

| Version | Date | Release | What changed | By |
|---|---|---|---|---|
| v11.0.0 | 11 Nov 2026, 19:00 IST | R11 | Part A built: bills and the prepared UPI payment, birthdays, top priority and pending; Needs I1 and owner checks | 🛠 Mark XIV |
| v11.0.1 | 11 Nov 2026, 20:33 IST | R11 | Review fixes: one card-number check, the payee's safe set and quotes, the typed-here UPI rule, month-end due days, pay / paid phrases for his bills only, guarded sweeps, fenced labels, the payment audit line; what was left and why (§5) | 🛠 Mark XIV |
