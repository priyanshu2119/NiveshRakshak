# NiveshRakshak — Adversarial Self-Review (pre-build)

Method: for every planned check, ask "wait, couldn't someone just—" from two seats:
(a) a fraudster trying to pass the system while still running a real scam, and
(b) a legitimate, currently-registered advisor trying not to be wrongly flagged.
Each scenario ends with the design response, and where the response is partial,
that is stated and carried into LIMITATIONS.md. The plan was revised *before*
implementation where noted.

---

## Scenario 1 — The IIFL pattern: real name, real registration number, fake channel
**Attack**: Fraudster impersonates a real Whole-Time Director of a real brokerage.
The message quotes a genuine registration number (INZ000031633-style) and a real
firm name — both pass any name-registry check. Money is requested to
`investments.brk@okhdfcbank` (a consumer-style handle they control).

**Would a name-check tool pass it?** Yes — that's the documented failure mode this
product exists for.

**Our design**: the headline is driven *only* by the payment-channel check. The
handle is not `@valid*` → RED FLAG headline, full stop. The registry match is
displayed *below*, explicitly labeled: "A firm by this name is registered with
SEBI — that does not prove this message came from them, and it does not make this
payment request safe." The card names the pattern: real credentials + unverified
payment channel = classic impersonation.
**Handled: YES** — this is the core case; precedence rules in `verdict.py` make it
structurally impossible for the secondary check to soften the headline.

## Scenario 2 — The look-alike handle: `zerodha.brk@validhdfc` typed by a scammer
**Attack**: Fraudster knows the format (it's public) and simply *types* a
plausible validated handle into the chat, hoping the victim (or a naive tool)
pattern-matches `@valid` and relaxes.

**Our design**: we never format-match for the verdict. Every `@valid`-shaped
handle is submitted to SEBI Check's live `validate.html`. A fabricated handle
returns `errorCode: UPI_ID_INVALID` (verified live during research) → RED FLAG
with the SEBI transactionId shown as evidence. Format analysis is used only for
*display* (category suffix parsing) and to route the check — never to conclude.
**Handled: YES.** Residual: if SEBI Check is unreachable, we say "couldn't verify"
— never "looks valid because the format is right."

## Scenario 3 — Category-suffix swap: "mutual fund" paying into a broker handle
**Attack**: Message claims "XYZ Mutual Fund AMC collection", but the payment
handle is `xyz.brk@validaxis` — or the reverse. Also covers: a *real* handle of
entity A presented as entity B ("pay into our sister concern's account").

**Our design**: two layers. (1) SEBI Check returns the entity's actual registered
`role`/name for a valid handle; we compare it against the claimed name/category in
the message. Mismatch → prominent caution: "The handle is genuine, but it belongs
to <actual entity/name>, not <claimed> — do not pay unless the official app of
<claimed entity> itself shows this exact handle." (2) Suffix-vs-claim mismatch
(claims MF, suffix `.brk`) is flagged as supporting evidence even before the live
check. A genuine handle whose entity name *matches* the claim passes cleanly.
**Handled: YES for detection.** Honest gap: we cannot prove *who sent the message*
— only where the money goes. The card says exactly that.

## Scenario 4 — False-positive risk: legitimate advisor mid-migration / legacy SIP
**Attack (seat b)**: A small registered Investment Adviser, or an AMC collecting an
*existing SIP* via a legacy mandate, legitimately uses an old non-@valid handle.
Do we wrongly brand them fraudsters?

**Our design**: the red-flag copy is about the **payment channel**, not the person:
"SEBI-registered intermediaries must collect investments through @valid handles.
This request doesn't use one — do not pay this way; use the official app/portal or
ask them for their @valid ID." Per the circular, old-handle collection was required
to stop by ~Dec 8, 2025 (T+180) *except* ongoing SIPs — so post-cutoff, an old
handle in a *new investment pitch* is non-compliant even if the entity is real,
and saying so is the truth, not a false positive. The registry block still shows
the entity is registered (if it is), and the transition deadline is policy-config,
so if an extension circular exists, wording recalibrates via one env var.
**Handled: YES, with honest nuance baked into copy.** The SIP carve-out is stated
in the card footnote when the entity is registry-matched.

## Scenario 5 — Scammer pre-tests their pitch against us (abuse seat)
**Attack**: Fraudster pastes their draft message into NiveshRakshak, sees which
red-flag phrases light up, rewords, re-tests, ships a "clean-scoring" pitch.

**Our design**: wording signals are *visibly secondary* and can never lift the
headline — the headline comes from infrastructure facts (SEBI Check, registry)
that rewording cannot change. There is **no numeric score** to optimize. Even a
perfectly reworded pitch still fails the primary check the moment it asks for
money to a non-@valid destination — and every investment scam must ask for money
somewhere. Rewording can only remove *supporting* chips, which the card labels as
non-decisive context.
**Handled: YES for the load-bearing path.** Partial: a scammer could learn to
avoid our specific Hindi/English phrase list — accepted, because that layer is
explicitly context, not verdict.

## Scenario 6 — Typosquatting: "Zerodha Broking Limted" / INZ000031634
**Attack**: One character off a real entity — deliberately (impersonation) or via
victim typo. Exact-match-or-nothing tools silently return "not found" (which
scammers can spin as "registry is down, trust me") or, worse, substring tools
return the real entity and display it as a match.

**Our design**: NEAR_MISS is a **first-class third state** (amber, own icon, own
copy): "This is close to — but not the same as — registered entity <real name,
real reg no>. Impersonators often change one letter. Treat as suspicious."
Registration numbers get Levenshtein≤2 comparison against the full local mirror;
names get normalized token-set fuzzy. A near-miss can never be displayed as a
match, and never as a plain not-found.
**Handled: YES.**

## Scenario 7 — QR swap: text says broker, QR encodes a personal UPI
**Attack**: Screenshot shows a professional-looking pitch naming a real broker,
but the embedded QR encodes `upi://pay?pa=9876543210@ybl` (fraudster's personal
handle). Victims scan without reading.

**Our design**: QR is decoded locally (zbarimg) and the `pa=` handle goes through
the *same* primary check as typed handles. When text-claimed entity and
QR-decoded destination disagree, the card shows both side by side and the
mismatch itself is flagged. The decoded destination always wins the headline —
because that's where the money actually goes.
**Handled: YES.**

## Scenario 8 — Data-source outage / silent-pass temptation
**Attack**: Not a fraudster — entropy. sebi.gov.in or siportal goes down, changes
layout, or rate-limits us into a captcha wall at demo time. A lesser tool either
hangs, or quietly omits the failed check and shows a clean-looking card.

**Our design**: every check carries an explicit `UNAVAILABLE` state that renders
as a slate "Couldn't verify right now" block with the reason (timeout / captcha
pending / rate-limited) and the instruction "treat with extra caution — absence of
a red flag here is NOT a green signal." The overall verdict can never be more
positive than its least-certain load-bearing input: if the primary check is
UNAVAILABLE, the headline is UNVERIFIABLE no matter how clean the registry looks.
Circuit breaker prevents hammering a struggling regulator endpoint.
**Handled: YES** — this is enforced in `verdict.py` precedence, not left to copy.

## Scenario 9 — Handle enumeration / privacy seat
**Attack**: Someone scripts our API to enumerate which `@valid` handles exist
(business intelligence), or submits victims' private screenshots that get stored
forever.

**Our design**: in-process token-bucket rate limit per client IP on /api/check;
SEBI's own captcha/rate gates pass through (enumeration at volume hits their wall,
not ours alone). Raw text/images are never persisted; audit rows keep only
extracted identifiers + verdicts, auto-purged at 90 days. No accounts, no
analytics, no third-party requests from the page (fonts self-hosted option noted).
**Handled: YES for a demo-scale product.** Honest gap: a determined enumerator can
rotate IPs — accepted; SEBI Check's own gates are the real backstop, and we add no
bulk-export surface.

---

## Plan revisions made as a result of this review
1. Added **claimed-entity vs SEBI-returned-entity comparison** to the primary
   check output (Scenario 3) — not just valid/invalid, but *whose* handle it is.
2. Made **UNAVAILABLE-poisons-headline** an explicit precedence rule in the verdict
   assembler (Scenario 8), with tests.
3. Added **QR-vs-text mismatch** as a distinct supporting flag (Scenario 7).
4. Kept **no-score policy** absolute; supporting layer renders as phrase chips with
   explanations, never weights (Scenario 5).
5. Added the **SIP carve-out footnote** to red-flag copy when the entity is
   registry-matched (Scenario 4).
6. Rate limiting + retention job promoted from "nice to have" to build items
   (Scenario 9).
