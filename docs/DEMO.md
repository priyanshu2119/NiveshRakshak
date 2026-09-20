# NiveshRakshak — Demo Narrative

The story a judge (or a first-time user) needs, using **real checks run against
live SEBI systems on 2026-09-20** — every transaction ID below is a genuine
SEBI Check `TXN` from this build's audit log.

---

## The pitch (realistic, modeled on the documented IIFL-2026 pattern)

> *"Hello Sir, I am Rohit Sharma, Senior Investment Advisor at **Zerodha Broking
> Limited (SEBI Reg INZ000031633)**. Our VIP research team gives **guaranteed 30%
> monthly returns**. Last chance to invest in special IPO allotment. Pay ₹50,000
> booking amount immediately to our verified UPI: **zerodha.invest.brk@validhdfc**.
> Withdrawal released in 24 hours. Don't tell anyone about this exclusive offer."*

Every credential in this message is real **except the thing that matters**:
`INZ000031633` genuinely is Zerodha Broking Limited's SEBI registration number
(verified live against SEBI's registry during this demo).

## What the obvious tool says

A name/registry-check tool looks up "Zerodha Broking Limited" and/or
INZ000031633 → **match found** → shows a reassuring green "SEBI Registered ✓".
The victim pays ₹50,000 to `zerodha.invest.brk@validhdfc`. Done. This is exactly
how the IIFL impersonation case (2026) and the pattern in SEBI's April 2025
fraud circular work: *real registration numbers, quoted by the wrong person.*

## What NiveshRakshak says (actual output, check #6)

```
STAMP:        DO NOT PAY · RED FLAG
HEADLINE:     Stop — don't pay this way
PRIMARY:      NOT VERIFIED · zerodha.invest.brk@validhdfc
              "This handle is shaped like a @valid handle, but SEBI Check does
              not recognise it. Anyone can type a handle that looks right — only
              SEBI's own check proves it. Treat this payment request as
              fraudulent."                                    TXN-MU9QSTQC-0AJI
REGISTRY:     Registered match found — ZERODHA BROKING LIMITED, INZ000031633
              (CONTEXT, NOT PROOF) + standing caveat: "That does NOT prove this
              message came from them — names and registration numbers can be
              quoted by anyone, including impersonators."
ALSO NOTICED: guaranteed returns ("30% month") · urgency ("Last chance") ·
              secrecy ("Don't tell") · amount ₹50,000
NEXT:         Don't pay. Ask for their @valid handle and check it here.
              Already paid? Dial 1930.
```

The registry match is displayed — honestly, it's real — but it is structurally
incapable of lifting the headline, because the headline belongs to the payment
channel, and SEBI Check itself (transaction `TXN-MU9QSTQC-0AJI`) says the handle
is not one NPCI ever issued.

## The control case: a genuine handle (check #7)

> *"Invest with Taurus Corporate Advisory Services Limited — pay via UPI
> **taurus.cf.brk@validaxis**."*

```
STAMP:    CHANNEL VERIFIED · @VALID
PRIMARY:  VERIFIED · taurus.cf.brk@validaxis
          SEBI Check says this belongs to: TAURUS CORPORATE ADVISORY SERVICES
          LIMITED · Reg. INZ000258036 · Stock Broker      TXN-MU9R01E5-MMS5
REGISTRY: Registered match found (cross-check of the SEBI-returned entity):
          same name, same reg no INZ000258036, 4 segment registrations
FOOTER:   "Verified destination ≠ safe investment…" (always present)
```

Two independent systems — NPCI/SEBI Check and the SEBI registry mirror — agree
on the same entity and registration number. (This handle was not typed in from
a guess: it was decoded from Taurus Group's own published QR code,
`docs/demo-assets/taurus-official-qr.png`, which the tool also ingests directly.)

## The QR-swap case (check #10) — the category trap

Upload the genuine Taurus QR image, with the message: *"Someone sent me this QR
saying it's for **mutual fund** investment."*

```
STAMP:    DO NOT PAY · RED FLAG  (in 379 ms)
PRIMARY:  VERIFIED · taurus.cf.brk@validaxis → TAURUS … Stock Broker
FLAG:     "Claimed category Mutual Fund ≠ handle's registered category
           Stock Broker. Genuine handle, mismatched story — do not pay unless
           the claimed entity's own official app shows this exact handle."
```

A real handle, wielded with a false story, still fails — per the brief's §5.2.3
rule that a category mismatch is a red flag *regardless* of the handle's
validity. The QR was decoded locally (zbarimg), so the check runs on where the
money *actually* goes, not on what the text claims.

## Why the payment-channel check is the load-bearing one

A name is text; a registration number is text; even a `@valid`-shaped string is
text — anyone can type any of them into a chat, and deepfake video can "prove"
the face that goes with them. What a scammer cannot do is make **NPCI issue them
a `@valid` handle**, because NPCI only issues those after independently
verifying the entity against SEBI's own registration data. That asymmetry is the
only part of this scam pattern that resists social engineering — so NiveshRakshak
makes it the headline, and demotes everything typeable to context.

## Live demo script (2 minutes)

1. `./run.sh` → open http://127.0.0.1:8300 (footer shows the live registry
   mirror: 23,452 entries, today's date).
2. Paste the Rohit Sharma pitch above → **Check it** → red flag in ~1–3s, with
   the real SEBI transaction ID under the primary result. Point at the registry
   section: *the real name matched, and it still says DO NOT PAY — that's the
   product.*
3. Upload `docs/demo-assets/taurus-official-qr.png` with "mutual fund" claim →
   category-mismatch red flag on a genuine handle.
4. Same QR, honest message → CHANNEL VERIFIED, two independent sources agreeing.
5. Toggle हिंदी — the whole card re-renders natively.
6. Tap **Share this verdict** / **Save as image** — the card travels back into
   the chat it came from.
7. "Zerodha Broking **Limted**" (one typo) as claimed name → amber
   **Suspicious near-match** box naming the real entity it imitates — its own
   third category, never folded into pass/fail.
