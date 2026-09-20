# NiveshRakshak — Design & Architecture Decisions

Every major choice below was made against researched alternatives (see RESEARCH.md),
not out of habit. Rationale is part of the deliverable.

---

## 1. Architecture

### Surface: mobile-first web app (not a WhatsApp/Telegram bot — yet)
Considered: (a) WhatsApp Business bot, (b) Telegram bot, (c) web app.
- WhatsApp Business API needs Meta business verification, template pre-approval,
  per-message cost — days-to-weeks of friction, and rich verdict cards render poorly
  inside message templates.
- Telegram bots are free/fast but the verdict experience is constrained to message
  bubbles, and image-based verdict cards get compressed.
- **Chosen: web app.** Zero approval friction; a link travels into any chat; the
  verdict card is designed to be *screenshotted and forwarded back into the same
  WhatsApp/Telegram thread* — which is exactly the spread mechanic the brief wants.
  The backend is a plain HTTP API, so a Telegram bot wrapper is a thin next step
  (documented in LIMITATIONS.md).

### Stack: Python 3.11 + FastAPI + SQLite + vanilla JS frontend
Considered: Next.js/React full-stack, Flask, Django, plain stdlib http.server.
- The hard parts of this product are **outbound integrations** (SEBI Check session
  dance, registry scraping, xls parsing, OCR/QR subprocesses, fuzzy matching) —
  Python owns all of those with the least code (requests sessions, xlrd, rapidfuzz,
  tesseract/zbar CLIs).
- FastAPI over Flask: async-friendly, built-in validation, auto docs, same footprint.
- SQLite over Postgres: single-file, zero-ops, stdlib `sqlite3`, WAL mode handles our
  concurrency; the audit log requirement ("auditable over time") is satisfied with
  append-only rows + retention job. Upgrade path documented if multi-instance.
- **Vanilla JS frontend, no build step**: one page, one flow. A framework would add
  a toolchain for zero user benefit (ponytail rung 4: native platform features).
  No npm install, no bundler, works offline once fonts are cached.
- OCR/QR via **CLI subprocesses** (tesseract, zbarimg) instead of Python bindings:
  both are installed, battle-tested, and avoid fragile native wheels (pytesseract is
  just a subprocess wrapper anyway; we call the real thing directly).

### Verification pipeline (the load-bearing design)
```
input (text | image | both)
  ├─ extract.py  → UPI IDs, bank acc+IFSC, phones, names, reg numbers, upi:// links
  ├─ ocr.py      → tesseract text (eng+hin) + zbarimg QR decode → merged into extraction
  ├─ PRIMARY: sebicheck.py → SEBI Check validate.html / accValidate.html (live)
  │     states: VERIFIED | INVALID (red flag) | CAPTCHA_PENDING | UNAVAILABLE
  ├─ SECONDARY: registry.py → live AJAX search + local SQLite mirror (exact)
  │     + rapidfuzz near-miss (own third state, never folded into pass/fail)
  ├─ SUPPORTING: redflags.py → pattern list (en/hi), never a numeric score
  └─ verdict.py → assembly with strict precedence:
        primary FAIL can never be overridden by secondary PASS (brief §5.2.3)
        secondary/supporting can never manufacture an all-clear (brief §5.5)
```

### SEBI Check client design (resilience is the feature)
- Persistent `requests.Session`; bootstraps `CA_SESSIONID` by GETting the portal page.
- WAF 505 → re-bootstrap session once, retry once.
- `X-Captcha-Required: true` / HTTP 432 → fetch `/captcha-data`, hand the image to
  the frontend, hold the pending challenge server-side (in-memory, 120s TTL matching
  `expiryMs`), submit the user's answer on the same session. **No bypass, no OCR
  auto-solve** — it's a regulator's anti-abuse gate; we respect it (and OCR proved
  unreliable in testing anyway).
- 429/420 → exponential backoff; after 3 consecutive failures a 5-minute circuit
  cooldown opens and the product says "couldn't verify right now" (never a silent pass).
- Result cache in SQLite (key = normalized UPI or SHA512(acc)+IFSC, TTL 6h) so a
  viral scam handle checked 100× hits SEBI once; cached verdicts are labeled with
  "last checked HH:MM" so freshness is visible, not hidden.
- A single lock serializes SEBI Check calls (session is stateful; captcha state is
  per-session). ponytail note: global lock; per-session pool if throughput matters.

### Registry mirror + near-miss
- `tools/refresh_registry.py` downloads the investor-facing category .xls exports
  (daily-updated by SEBI) → parses with xlrd → upserts into SQLite.
  Runs on first boot and whenever the mirror is >24h stale (checked at startup,
  manual endpoint for demo control).
- Exact/substring lookups: **live AJAX first** (freshest), local mirror as fallback
  when sebi.gov.in is unreachable — result is labeled with which source answered and
  the mirror's as-of date. Graceful degradation per brief §5.3.4.
- Near-miss: rapidfuzz over normalized names (case/punctuation/suffix-stripped:
  pvt ltd/limited/private etc.) + Levenshtein ≤2 on registration numbers.
  Thresholds tuned so "Zerodha Broking Limted" and "INZ000031634" (one digit off a
  real reg no) both land in NEAR_MISS — its own amber category, never silently
  folded into pass or fail (brief §5.4).

### Storage & privacy (brief §7)
- `checks` audit table: timestamp, extracted identifiers (UPI/acc+IFSC/name/regno),
  verdict states, SEBI transactionId, source, cached flag. **Raw message text and
  uploaded images are processed in memory and never persisted.**
- Retention: audit rows auto-purged after 90 days (startup task + daily).
- No accounts, no cookies beyond a CSRF-ish same-site fetch posture, no analytics.

### Speed budget (brief §7)
- Extraction + red flags: <10ms. Near-miss vs ~30k registry rows: <50ms (rapidfuzz).
- SEBI Check live call: 1–3s typical. OCR: 1–3s. QR: <300ms.
- Independent checks run concurrently (threads); total target <5s worst case,
  ~2s typical text-only check. UI shows per-check progress so it *feels* instant.

## 2. Visual identity (researched, then decided)

Research inputs: (a) SEBI's own validated-handle visual language — the **white
thumbs-up inside a green triangle** — is what users will see inside their UPI apps
at the moment of truth; echoing it builds recognition transfer. (b) Government
trust cues in India: stamps, registration numbers, receipt-like documents (the
circular itself mandates QR + handle display). (c) Fraud-app clichés to avoid:
red-black alarmism, siren emojis, shield-with-keyhole gradients, dark-mode neon —
these read as scammy themselves to low-digital-literacy users and induce panic the
brief explicitly warns against. (d) Accessibility: WCAG 2.2 AA contrast, one idea
per screen, 16px+ body type, big touch targets.

Decisions:
- **Paper-and-stamp aesthetic**: warm paper background (#F7F3EC), ink-dark text
  (#1C1B19), verdict card styled like a stamped receipt — perforated edge, monospace
  transaction ID (echoing SEBI Check's own TXN-… ids), a rotated stamp motif for the
  verdict. Familiar, official-feeling, calm — and visually nothing like AI-template
  SaaS (no gradients, no glassmorphism, no purple).
- **Color = verdict semantics only**: verified green #157F3D (deliberately close to
  the SEBI triangle green), red flag #B3261E, caution/near-miss amber #9A6700,
  couldn't-verify slate #5B6470. Four states, four colors, used nowhere else — so
  color itself becomes legible information (helps color-anxious users; each state
  also carries icon + word + shape, never color alone).
- **Typography**: "Anek Devanagari" (Indian variable typeface family — distinctive,
  designed for exactly this multilingual context) for display; "IBM Plex Sans" for
  body (humanist, excellent Devanagari companion via Noto Sans Devanagari fallback);
  "IBM Plex Mono" for IDs/numbers. Loaded with `font-display: swap` + system
  fallbacks so low bandwidth degrades gracefully.
- **Iconography**: custom inline SVG set (shield-check, triangle-thumbs echo,
  magnifier, warning-stamp) drawn for this product — no icon library, no emojis in
  verdict positions.
- **Motion**: one purposeful micro-interaction — the verdict stamp "presses" onto
  the card (250ms scale+rotate), honoring `prefers-reduced-motion`. Nothing else moves.

## 3. Tone & copywriting

Research inputs: effective consumer safety products (bank fraud alerts, Google
Safe Browsing interstitials, SEBI's own investor copy) share: short declarative
sentences, one action per screen, no jargon, no probability numbers, and they
separate *what we know* from *what you should do*. Panic copy ("FRAUD DETECTED!!!")
causes denial; vague copy ("some risk observed") causes inaction.

Decisions (applied to every string in `web/i18n.js`):
- Headline states the payment-channel fact first, in plain words:
  "This payment is NOT going to a SEBI-verified handle" — not "risk score 87".
- Calibrated certainty everywhere (brief §3 honesty constraint): during/after the
  transition we say "serious red flag — do not pay this way" and never "100% fraud
  proof"; verified says "this destination is the registered, accountable place it
  claims to be — it does NOT mean the investment itself is safe or good" (the
  verified≠safe distinction is a permanent footer line on every verified card).
- Registry matches always carry the identity caveat in the same breath: "A firm by
  this name is registered with SEBI. That does NOT prove this message came from them."
- Near-miss gets its own voice: suspicious, specific, shows the real entity it
  resembles.
- Bilingual EN/हिं toggle; Hindi copy is written natively (not machine-translated
  legalese), Hinglish-friendly where that's how people actually type.
- Every verdict ends with ONE next action ("Don't pay. Ask them for their @valid
  UPI ID and check it here." / "You may proceed through the official app only."),
  plus the 1930 cyber-crime helpline where relevant.

## 4. Abuse-resistance review (brief §7)

- The headline verdict derives **only** from SEBI Check (NPCI-issued handles) and
  registry facts — a scammer cannot tune message wording to flip it. Wording-level
  signals (redflags.py) are visibly secondary and can never raise the headline.
- There is **no numeric score** anywhere — nothing to optimize against.
- Rate limiting on our own API (slowapi-style in-process token bucket) so the tool
  can't be used to bulk-enumerate handles; SEBI's own captcha/rate gates are passed
  through, never circumvented.
- Cache is keyed on normalized identifiers with 6h TTL — an attacker can't poison
  it (values come from SEBI, not users).

## 5. What we deliberately did NOT build (and why)

- No LLM dependency: extraction targets are structured (UPI/IFSC/regno/phones) and
  rule-based extraction is deterministic, free, offline, and un-poisonable. An LLM
  would add latency, cost, nondeterminism, and a prompt-injection surface for zero
  gain on the load-bearing path. (Upgrade path: optional LLM pass for *name*
  extraction from very messy text, behind a flag.)
- No complaint-history feature: SCORES per-entity data isn't public (RESEARCH §4).
  Faking it would violate the product's own honesty rule.
- No user accounts/history UI: privacy-first; the audit log is operator-side.
- No mobile app: web installable (add-to-home-screen) covers the demo and the use
  case; app stores add weeks.
