# NiveshRakshak — Research Log

Everything below was verified with live tools (curl, browser, PDF extraction, QR decode)
on **2026-09-20**. Confidence levels: HIGH = primary source verified directly,
MEDIUM = one credible secondary source, LOW = could not fully confirm.

---

## 1. The @valid UPI handle system (PRIMARY CHECK foundation)

### Verified from the official circular PDF (HIGH)
Source: `https://www.sebi.gov.in/sebi_data/attachdocs/jun-2025/1749641449497.pdf`
Circular **SEBI/HO/DEPA-II/DEPA-II_SRG/P/CIR/2025/86**, dated **June 11, 2025** —
"Adoption of Standardised, Validated and Exclusive UPI IDs for Payment Collection by
SEBI Registered Intermediaries from Investors" (15 pages, read in full).

- **Handle format**: `username.categorysuffix@validbankname`
  - Username is generated through the SI Portal utility so it matches the entity's
    business name; allocation is subject to availability.
  - The same username can be valid across multiple banks
    (circular's own example: `abc.brk@validhdfc` and `abc.brk@validicici`).
  - Username may contain dots (verified empirically: Taurus uses `taurus.cf.brk`).
- **Category suffixes (Annexure B, authoritative list)**:
  | Intermediary type | Suffix |
  |---|---|
  | Stock Brokers (all segments) | `brk` |
  | Banker to an Issue | `bti` |
  | Depository Participants | `dp` |
  | Research Analyst | `ra` |
  | Investment Adviser | `ia` |
  | Infrastructure Investment Trust | `invit` |
  | Mutual Fund | `mf` |
  | Portfolio Manager | `pms` |
  | SM REIT | `sreit` |
  | Real Estate Investment Trust | `reit` |
- **Eligible banks (Annexure C)**: 52 Self-Certified Syndicate Banks (AU SFB … SBI).
  Observed real handle suffixes: `@validhdfc`, `@validaxis`, `@validicici`, `@validkpay`.
- **Timeline (Section 7 of circular, T = June 11, 2025)**:
  - Validated IDs available to investors **w.e.f. October 01, 2025** (Section 8).
  - Intermediaries obtain @valid handles: T+90 → T+105 days.
  - **Discontinuation of old UPI IDs: end = T+180 days ≈ December 8, 2025.**
  - **Permanent carve-out (Para 6.1.3)**: ongoing MF SIPs continue on the old mode;
    only new/renewed SIPs must use new UPI IDs. This carve-out has no end date in
    the circular — old handles can legitimately persist for existing SIP mandates.
- **Visual marker**: white thumbs-up inside a green triangle on the payment
  confirmation screen and on the mandated QR code (circular FAQ, investor section).
- QR generation with the thumbs-up logo is **mandatory** for intermediaries.

### ⚠️ Discrepancy vs the project brief (stated explicitly, per brief §11)
The brief claims legacy handles phase out "around **December 11, 2026**" and says to
verify. **I could not confirm that date from any primary source.**
- The circular's own table says T+180 days = **Dec 8, 2025** (already passed as of
  today, Sep 20, 2026).
- June 11, 2025 + 18 months = Dec 11, 2026 — the brief's date looks like an
  18-month reading of the timeline; no amendment circular extending to Dec 2026 was
  found on sebi.gov.in (site search + Google News RSS, multiple queries) or in news.
- News as recent as **Sep 17, 2026** (Economic Times: "Sebi to examine discount
  brokers' concerns over new UPI MDR") shows the validated-UPI system live and in
  active commercial use.
- HDFC Bank's investor notice (current as of fetch) uses strong present tense:
  "A UPI ID that is NOT @valid is fraudulent."

**Design consequence**: the transition deadline is a **configurable policy parameter**
(`server/policy.py`, env-overridable), never a hardcoded fact. Default posture today:
cutoff has passed → non-@valid investment payment request = serious red flag with
near-absolute wording, minus the SIP carve-out nuance. If an amendment surfaces,
one env var flips the wording back to transition-period calibration.

### Real handle verified end-to-end (HIGH)
- Downloaded Taurus Group's official UPI QR images from `taurusgrp.com/ValidUPIHandles`,
  decoded with `zbarimg`:
  - `upi://pay?pa=taurus.cf.brk@validaxis&cu=INR`
  - `upi://pay?pa=taurus.cf.dp@validaxis&cu=INR`
- Confirms: QR deep-link format, dot-containing usernames, `cf` appearing inside the
  username portion (parser must treat only the **last** dot-segment before `@` as the
  category suffix, and even that only if it is in the Annexure B set).

## 2. SEBI Check — the verification mechanism (reverse-engineered, HIGH)

Portal: `https://siportal.sebi.gov.in/intermediary/sebi-check`
(mirrored from www.sebi.gov.in header widget: Scan QR / Type / Account).
11 languages supported on the portal itself (en, hi, mr, gu, ta, bn, te, kn, ml, or, pa).

### API contract (verified by reading the portal's own JS + live curl tests)
Session: `GET /intermediary/sebi-check` first → sets `CA_SESSIONID` cookie.
POSTs without session+headers are WAF-blocked with **HTTP 505** (verified).

**UPI check** — `POST /intermediary/sebi-check/validate.html`
- multipart form: `ctype=upi-check`, `upi=<id>`, `captcha=<text or empty>`
- headers: `X-Requested-Via: SI Portal`, `X-Requested-With: XMLHttpRequest`,
  Referer/Origin of the portal, browser UA.
- Response JSON (verified live for invalid handle):
  ```json
  {"status":"error","message":"UPI Id is not valid!",
   "requestData":{"cType":"upi-check","upiId":"...","ifsc":null,"accNo":null},
   "errorCode":"UPI_ID_INVALID","transactionId":"TXN-MU9MIT1D-TGBA",
   "isTemplateUpiId":null,"entity":null}
  ```
- Success schema (from portal's `manual-check.js`, not yet observed live — captcha
  gate hit during testing; build parses defensively):
  `{"status":"success","entity":{"name","regNo","role","desc","legalAccHolderName"},"transactionId"}`

**Account check (NEFT/RTGS)** — `POST /intermediary/sebi-check/accValidate.html`
- multipart: `ctype=account-check`, `ifsc=<IFSC>`, `accNo=<SHA-512 hex of account
  number>`, `captcha=`. The SHA-512 hashing is done client-side by the portal's own
  `fetchAccNo()` (verified in `account-check.js`) — trivially replicable server-side.
- Client-side validation the portal itself applies: IFSC `^[A-Za-z]{4}0[A-Za-z0-9]{6}$`,
  accNo alphanumeric.
- Success entity includes `legalAccHolderName`, `accountNo`, `ifsc`; failure renders
  "No Match Found".

**Captcha** — `GET /intermediary/sebi-check/captcha-data`
- Returns `{imageBase64 (PNG 179×58), audioBase64 (WAV 16kHz mono), expiryMs: 120000,
  maxFailedAttempts: 3}` (all verified live).
- Becomes required after a handful of requests from an IP (observed: ~6 requests →
  `x-captcha-required: true` response header; subsequent POSTs without captcha → HTTP 432).
- Status codes (from portal JS + live observation): **419** captcha expired,
  **420** too many failed attempts, **429** rate limited, **432** captcha missing,
  **433** captcha incorrect, 400/500 generic.
- Response header `X-Captcha-Required: true|false` tells the client when to show it.

**Product consequence**: captcha is **passed through to the user** (image rendered in
our UI, answer forwarded with the same session). We do not bypass or auto-solve —
OCR-solving a regulator's captcha would be abusive and fragile (tested OCR: unreliable).

## 3. SEBI intermediary registry (SECONDARY CHECK foundation, HIGH)

### Live search AJAX (verified live)
`POST https://www.sebi.gov.in/sebiweb/ajax/other/getrecognisedintm.jsp`
- body (form-urlencoded): `intmId=<category or empty=all>`, `search=<name/trade name>`,
  `regNo=<registration no>`
- Returns HTML cards. Fields observed: Name, Trade Name, Registration No., Type,
  E-mail, Telephone, Address, Validity ("Mar 11, 2016 - Perpetual"), Exchange Name.
- Verified: `search=zerodha` → ZERODHA BROKING LIMITED, **INZ000031633**, multiple
  segment entries. Matching is **substring-based** ("taurus" matched "CEN*TAURUS*") —
  good for recall, useless for typo/near-miss detection → hence the local mirror below.

### Full-registry Excel exports (verified live)
`POST https://www.sebi.gov.in/sebiweb/other/IntmExportAction.do?intmId=<N>`
→ real .xls (CDFV2), `Content-Disposition: "Registered Stock Brokers in equity
segment as on Sep 19 2026.xls"` — **updated daily**. Brokers-equity file: 1.9 MB.

Category map (intmId → type), extracted from the Recognised Intermediaries page:
2 brokers-commodity, 4 designated DPs, 5 banker to an issue, 6 debenture trustee,
7 CRA, 8 KYC agency, 9 merchant bankers, 10 RTA/STA, **13 Investment Adviser**,
**14 Research Analyst**, 15 qualified DPs, **16 AIFs**, 18 DPs-CDSL, 19 DPs-NSDL,
20 InvITs, 21 VCFs, **23 Mutual Funds**, 25 FVCI, 27 custodians, 29 FPIs,
**30 brokers-equity (4,994)**, 31 brokers-equity deriv (3,789), 32 brokers-currency
deriv (2,698), **33 Portfolio Managers**, 34/35/44/45 SCSBs-ASBA, 37 brokers-debt,
38 brokers-IRD, 40/41 SCSBs-UPI, 42 REITs, 43 UPI apps for public issues,
46 vault managers, 47 ESG rating providers, 48 SM REITs.

**Product consequence**: nightly/on-demand refresh downloads investor-facing
categories into local SQLite → exact match + rapidfuzz near-miss detection run
locally in milliseconds, and the live AJAX endpoint remains the freshness fallback.
If both are down → honest "couldn't verify" state (never a silent pass).

### Registration number formats (observed)
- Brokers/clearing: `INZ000031633` (INZ + 8 digits)
- Investment Advisers: `INA…`, Research Analysts: `INH…`, PMS: `INP…`, MFs: `INF…`
  (pattern `IN[A-Z]\d{8}`; older exchange-member formats also exist in the wild).

## 4. SCORES complaint history (supporting layer — honest finding)

- SCORES 2.0: `https://scores.sebi.gov.in` (old scores.gov.in closed **March 28, 2024**).
- Public "Entity Status" page shows: entity name, status, state, email, exchange
  status — **registration status only**.
- **Per-entity complaint counts/history are NOT publicly visible** without login
  (verified by inspecting the public portal pages). SEBI publishes aggregate
  monthly/annual disposal reports only.
- SEBI "Investor Alerts" page (`investor-alerts.html`) renders as an empty shell —
  no usable public data endpoint found.

**Product consequence (per brief §5.5 "be honest if visibility turns out partial")**:
we do NOT fake a complaint-history feature. The supporting layer instead cross-checks
the claimed entity against the **full downloaded registry** (a claimed "advisor" who
appears nowhere in any category is a documented, verifiable red flag) and shows the
registry's own Validity/Type fields. The UI states plainly that complaint-level data
is not public.

## 5. Fraud statistics (brief §2 verification)

- **₹22,495 crore lost to cyber fraud in 2025, ~28.15 lakh cases, 24% YoY case
  spike, investment scams >75% of losses** — confirmed: ThePrint, Feb 21, 2026
  ("Cybercrime saw 24% spike in 2025…") + Lok Sabha Unstarred Question No. 1349
  answered Feb 11, 2026 ("Sharp rise in cyber and financial frauds"). HIGH.
- **SEBI AI-driven multilingual calling campaign to promote SEBI Check + validated
  handles, launched mid-Feb 2026** — confirmed: sebi.gov.in official page dated
  **Feb 13, 2026**. HIGH. (Also confirms the brief's read: SEBI itself is spending
  on awareness because public awareness is still low.)
- IIFL impersonation alert (fraudsters using a real Whole-Time Director's name +
  forged credentials + deepfake): consistent with SEBI's April 2025 fraud circular
  pattern; treated as MEDIUM (not independently re-fetched — used only as narrative
  motivation, not as a product dependency).

## 6. Delivery-channel research (brief §8)

- WhatsApp Business Platform: template messages need pre-approval; a verification
  bot is possible but needs Meta business verification + per-message pricing +
  approval timeline (days–weeks) — not viable inside this build window.
- Telegram Bot API: free, instant bot creation, but requires a public bot token and
  Telegram's TOS; also not where the *decision moment* UI can be richest.
- **Decision**: mobile-first **web app** as the primary surface (zero approval
  friction, works from any chat via a shared link, screenshot-friendly verdict card
  travels back into WhatsApp/Telegram chats natively). A Telegram bot wrapper is the
  documented next step (thin client over the same HTTP API).

## 7. Local toolchain verified (all present on this machine)

- Python 3.11.9 (pyenv), Node v26.9.0
- tesseract 5.5.3 (`/usr/bin/tesseract`) — eng+hin traineddata downloaded into repo
- zbarimg (QR decode — verified working on the Taurus QRs)
- ImageMagick (magick/convert/identify), pdftotext
- Installed into project venv: fastapi 0.141.1, uvicorn 0.53.0, requests 2.34.2,
  rapidfuzz 3.14.6, xlrd 2.0.2, pillow 12.3.0, python-multipart 0.0.32
