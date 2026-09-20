# NiveshRakshak — Honest Limitations

Written in the spirit the brief demands: no overselling. Each item states the
gap, why it exists, and what would close it.

---

## 1. Regulatory-date uncertainty (the biggest honesty item)

The brief claimed legacy handles phase out "around **December 11, 2026**". I
could not confirm that date from any primary source. The circular itself
(SEBI/HO/DEPA-II/.../CIR/2025/86, read from the official PDF) sets
discontinuation at **T+180 days ≈ December 8, 2025** — already past as of build
date (Sep 20, 2026) — with a **permanent carve-out for ongoing MF SIP mandates**.
No extension circular was found on sebi.gov.in or in news searches.

**Consequence**: the product defaults to post-cutoff (strict) wording for
non-@valid handles, tempered by the SIP carve-out note when the entity is
registry-matched. If an amendment exists that I missed, one env var
(`NR_LEGACY_CUTOVER` / `NR_STRICT_MODE=transition`) recalibrates every verdict's
certainty language — the design never hardcodes this as a fact.
**Next**: subscribe to SEBI circular RSS / re-verify monthly; if Dec 2026 is
real, flip the policy default.

## 2. SEBI Check is an undocumented, unversioned endpoint

The `validate.html` / `accValidate.html` contract was reverse-engineered from
the portal's own JavaScript and verified live — but SEBI can change it, add
stricter bot detection, or geo/IP-gate it without notice. Mitigations built in:
defensive parsing (unknown error codes → "couldn't verify", never a false
pass), WAF-505 session re-bootstrap, circuit breaker, honest UNAVAILABLE state.
**Next**: a contract canary (scheduled probe asserting the known response shape)
that alerts the operator when SEBI changes something; a fallback path to the
www.sebi.gov.in mirror of the checker.

## 3. Captcha pass-through is built but was not exercised end-to-end in demo

SEBI's captcha gate triggered during research (HTTP 432/433 observed live, and
`captcha-data` image+audio verified), and the full pass-through flow is
implemented (image rendered in-UI, answer forwarded on the same session, 120s
TTL, refresh button). But during final E2E testing SEBI stopped gating this IP,
so the solve-loop wasn't demoed live. OCR auto-solving was deliberately **not**
built (unreliable in tests, and bypassing a regulator's anti-abuse gate would be
wrong). **Next**: exercise the loop once the gate re-triggers; consider the
audio captcha for accessibility (it's already fetched — expose a play button).

## 4. Shared-session concurrency ceiling

One SEBI Check session, serialized behind a lock (captcha state is
session-scoped). Fine for single-instance/demo load; under real concurrent
traffic, users would queue and captcha challenges could cross-contaminate.
Marked in code (`ponytail:` comment). **Next**: per-user session pool keyed by
client id, or a small worker queue.

## 5. Complaint history: not faked, therefore absent

SCORES per-entity complaint counts are **not public** (verified: the public
portal exposes only registration-style "Entity Status"). SEBI's Investor Alerts
page renders as an empty shell with no usable data endpoint. Rather than invent
a complaint feature, the supporting layer cross-checks claims against the full
23.5k-row registry and says plainly what it can't see. **Next**: if SEBI opens
SCORES aggregates (or via RTI datasets), add it as another supporting signal;
SEBI enforcement/adjudication-order search is a scrapeable interim option.

## 6. Extraction is rule-based: strong on structure, weak on free-form names

UPI/IFSC/account/phone/regno/deep-link extraction is deterministic and tested
(incl. `(at)` obfuscation, zero-width stripping, email disambiguation, Hindi
keywords). But *claimed entity names* rely on capitalized-sequence heuristics —
Devanagari-script names aren't extracted from message text (the optional
claimed-name field covers this, and the UI says so). An LLM pass would improve
name extraction on very messy text; deliberately not added (cost, latency,
nondeterminism, prompt-injection surface — DECISIONS.md §5). **Next**: optional
LLM name-extraction behind a flag, with the rule-based path as fallback.

## 7. OCR quality ceiling

Tesseract (eng+hin, fast traineddata) on phone screenshots: works on clean
renders (verified: decoded text + QR from real images), but low-contrast,
rotated, or heavily compressed WhatsApp screenshots will degrade. QR decoding
(zbarimg, with 2× upscale retry) is the reliable path for payment data in
images — QRs carry the handle structurally. **Next**: better preprocessing
(adaptive thresholding), or the `hin`/`eng` "best" traineddata (slower, more
accurate); a client-side canvas upscale pass.

## 8. Language coverage: EN + HI, honestly labeled

Full UI + verdict copy + red-flag patterns exist for English and Hindi
(Hinglish-tolerant). The other 9 languages SEBI Check itself supports are not
covered — the product states what it supports rather than pretending.
Extraction of payment identifiers is script-independent (Latin digits/VPAs), so
a Tamil/Telugu message with a UPI ID still gets the load-bearing check; only
the linguistic layer and UI copy are limited. **Next**: mr/gu/ta/te/bn UI packs
(the i18n dictionary is the only file to touch per language).

## 9. Registry mirror freshness & scope

The mirror refreshes from SEBI's daily exports (25 investor-facing categories,
23,452 rows at build time) at startup when >24h stale. Between refreshes, a
same-day registration change could be missed; the live AJAX endpoint (used as
fallback when the mirror is empty) has the same daily cadence anyway. FPI/SCSB
categories are excluded by design (not retail pitch targets). Every verdict
shows the mirror's as-of timestamp. **Next**: cron the refresh; add a
"freshness age" warning past ~36h.

## 10. Fuzzy-matching thresholds are tuned, not proven

Near-miss uses token_set_ratio ≥ 88 (names) and Levenshtein ≤ 2 (reg numbers) —
tuned against real registry shapes and tested (typos caught, unrelated names
rejected), but no labeled impersonation corpus exists to measure precision/
recall. A near-miss is deliberately *loud but non-terminal* (amber, own
category, never blocks a verified channel). **Next**: collect real near-miss
sightings via the audit log and re-tune.

## 11. What the product fundamentally cannot do

- **Prove who sent a message.** It verifies where money would go, and whether
  claimed identities exist/are being imitated — sender identity is out of scope
  for any tool, and the copy never implies otherwise.
- **Judge investment quality.** A verified destination can still sell a bad or
  unsuitable product; the "verified ≠ safe investment" line is permanent on
  every card by design.
- **Stop a determined scammer.** It can only arm the person about to pay —
  which, per the brief's own framing (≈45% of operations run from overseas),
  is the realistic win condition.

## 12. Deployment posture

Local-first (127.0.0.1) by design; no public tunnel was opened during the build
(confirmation-gate policy). The HTTP API is bot-wrappable (a Telegram thin
client is the documented next step), rate-limited per IP, and CSP-locked with
self-hosted assets — but a public deployment would additionally want: TLS
termination, per-instance rate-limit storage (currently in-process), and
abuse monitoring of the audit log.
