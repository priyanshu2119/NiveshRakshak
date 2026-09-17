# NiveshRakshak (निवेशरक्षक)

**Check where the money actually goes — before you pay.**

Investment scams are India's largest cyber-fraud category (₹22,495 crore lost in
2025; >75% of all cyber-fraud losses). The playbook always ends the same way:
money sent to a UPI handle or bank account in a chat. NiveshRakshak takes that
chat message / screenshot / QR / UPI ID and answers one load-bearing question
first — **is this payment destination one NPCI independently verified as a real,
currently SEBI-registered entity?** — with everything else (registry name match,
near-miss detection, scam-language patterns) explicitly presented as context,
never as proof.

The output is a screenshot-ready **verdict card** meant to be forwarded straight
back into the WhatsApp/Telegram group the pitch came from.

## Run it

```bash
./run.sh                 # → http://127.0.0.1:8300
```

Requirements: Python 3.11+, `tesseract` and `zbarimg` on PATH (screenshot/QR
intake; text-only checks work without them). First boot downloads SEBI's
daily-updated registry exports (~23.5k entries across 25 categories) into a
local SQLite mirror — needs network to sebi.gov.in and siportal.sebi.gov.in.

Environment knobs (all optional):

| var | default | meaning |
|---|---|---|
| `PORT` / `HOST` | 8300 / 127.0.0.1 | bind address |
| `NR_STRICT_MODE` | `auto` | `auto` (strict after cutoff) · `transition` · `strict` — wording policy for legacy handles |
| `NR_LEGACY_CUTOVER` | `2025-12-08` | legacy-handle discontinuation date (T+180 of circular 2025/86; see docs/RESEARCH.md §1 — the brief's "Dec 11 2026" could not be confirmed) |
| `NR_RATE_LIMIT` / `NR_RATE_WINDOW` | 30 / 600 | per-IP checks per window |
| `NR_RETENTION_DAYS` | 90 | audit-log retention |
| `NR_DB` | `data/nr.sqlite` | database path |

## How a check runs

```
message / screenshot / QR
  → extract.py    UPI handles (incl. "(at)" obfuscation, zero-width stripping),
                  upi:// links, account+IFSC, phones, reg numbers, claimed names
  → ocr.py        tesseract (eng+hin) + zbarimg QR decode
  → PRIMARY       sebicheck.py → SEBI Check live API (validate.html /
                  accValidate.html), captcha passed through to the user,
                  circuit breaker, 6h result cache
  → SECONDARY     registry.py → live SEBI AJAX search + local mirror of the
                  official .xls exports; rapidfuzz near-miss = its own state
  → SUPPORTING    redflags.py (EN/HI scam-language patterns, no score) +
                  cross-checks (claimed vs SEBI-returned entity/category/QR payee)
  → verdict.py    strict precedence: a failed primary can never be overridden
                  by a clean secondary; an unavailable primary poisons the
                  headline (never a silent pass)
```

## What it will never claim

- "Verified" means **the destination is the registered, accountable place it
  claims to be** — never "safe investment". The distinction is a permanent line
  on every card.
- A registry name match never implies the message came from that entity.
- Near-misses are never silently folded into pass/fail.
- Unreachable sources produce an honest "couldn't verify — treat with extra
  caution", never a clean-looking result.

## Docs (part of the deliverable)

- `docs/RESEARCH.md` — every regulatory/technical fact, verified against primary
  sources on 2026-09-20, with discrepancies vs the project brief flagged
- `docs/DECISIONS.md` — architecture, visual identity, tone: choices + rationale
- `docs/ADVERSARIAL-REVIEW.md` — 9 attack/false-positive scenarios and how the
  design answers each
- `docs/DEMO.md` — demo narrative (the IIFL-pattern case a name-checker misses)
- `docs/LIMITATIONS.md` — honest gaps and next steps

## Tests

```bash
.venv/bin/python -m pytest tests/ -q          # offline unit tests
.venv/bin/python -m pytest tests/ -q -m live  # hits real SEBI endpoints (sparingly)
```

## Privacy

Messages and images are processed in memory and **never persisted**. The audit
log keeps only extracted identifiers (UPI destinations, masked accounts/phones,
verdict states, SEBI transaction IDs) for 90 days, then auto-purges. No
accounts, no analytics, no third-party requests — fonts and scripts are
self-hosted, CSP locked to `'self'`.

## Independence

Not affiliated with, endorsed by, or part of SEBI or NPCI. Uses their public
interfaces the same way a browser does; SEBI's captcha and rate gates are passed
through to users, never bypassed.
