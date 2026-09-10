# Magic-Link Self-Serve Access — Plan

**Status:** Planned / not started. Written 2026-09-09.
**Goal:** Let new users get access to live-faktencheck.de on their own (self-serve),
without Ulf manually minting and handing out access codes.

## Core idea

The existing `codes` table **is** the accounts table. Each row already carries an
identity (`name`), per-user quotas (`quick_check_limit`, `audio_seconds_limit`),
and usage counters. Magic links do **not** replace this — they add a second,
self-serve way to *mint a code row* and hand it to the browser.

Once a link is clicked, the browser ends up holding a code, and everything
downstream is **identical to today**: the `X-Access-Code` header, `require_code`,
quotas, and the whole frontend unlock flow keep working unchanged.

```
enter email → POST /api/auth/request-link → email arrives
click link  → GET /api/auth/verify (consume token, find-or-create code row)
            → redirect /verify?code=XYZ → setAccessCode(XYZ) → app unlocked
(every later request: X-Access-Code: XYZ — unchanged from today)
```

## Backend changes

### 1. New table: `magic_links` (pending, one-time-use tokens)

```sql
CREATE TABLE IF NOT EXISTS magic_links (
    token       TEXT PRIMARY KEY,   -- random urlsafe, >= 32 bytes (secrets.token_urlsafe)
    email       TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    expires_at  TEXT NOT NULL,      -- created_at + 15 min
    consumed_at TEXT,               -- NULL until clicked; set on use (one-time)
    request_ip  TEXT                -- for IP-based rate limiting
);
```

### 2. Extend `codes` with an email identity

Add alongside the existing idempotent migrations in `database.py`:

```python
"ALTER TABLE codes ADD COLUMN email TEXT",
```

- The **code** is the session credential (what the browser stores + sends).
- The **email** is the durable identity. One email → one code row.
  On repeat signups, look up by email and reuse the existing row instead of
  minting a new code.

### 3. New router `routers/magic.py` — two **ungated** endpoints (front door)

```
POST /api/auth/request-link   { email }        -> 202 ALWAYS
GET  /api/auth/verify?token=…                  -> validate, consume, redirect
```

**`request-link`:**
1. Rate-limit first (see below). If throttled, still return 202.
2. Create a `magic_links` row (fresh token, expires +15 min, store request IP).
3. Email the link: `https://live-faktencheck.de/verify?token=<token>`.
4. **Always return 202**, even for unknown/garbage emails — never leak who is
   registered, never give an attacker feedback.

**`verify`:**
1. Load token → reject if missing / expired / already `consumed_at`.
2. Stamp `consumed_at` (one-time use).
3. **Find-or-create** the code row for that email: reuse existing `add_code(...)`
   with a generated code (`secrets.token_urlsafe`) + default quotas; store email.
   (`add_code` uses `INSERT OR IGNORE` with code as PK, so a fresh random code is
   collision-safe.)
4. Redirect to `https://live-faktencheck.de/verify?code=<code>`.

### 4. Email sending (the only genuinely new moving part)

No mail dependency exists today. Use a transactional email API over HTTPS
(Resend / Postmark / Brevo) — avoids running SMTP on the VPS.
- One helper `send_magic_link(email, url)`.
- API key in `.env` next to the others (`ASSEMBLYAI_API_KEY`, etc.).
- **Set up SPF + DKIM on the domain** — deliverability (links landing in spam)
  is the #1 failure mode for magic links.

### 5. What does NOT change

- `auth.py::require_code` and its use as a dependency on every gated route.
- Quota columns + `increment_*` methods.
- `seed_codes_from_env` — keep it; Ulf's own admin/press codes still work.
  Magic-link codes live alongside seeded ones.

## Rate limiting (required — closes the one new security hole)

`request-link` is ungated by necessity (no code exists yet), so anyone can call
it and each call sends an email to whatever address is in the body. Two abuses:

1. **Email bombing** a third party (flood victim's inbox; our domain gets blamed).
2. **Reputation/cost damage** to us (provider suspends us, sender reputation
   tanks so legit links go to spam, per-email billing runs up).

**Fix — cap before sending, on two axes:**
- Per **email**: max ~3 links / hour.
- Per **IP**: max ~10 requests / hour.

**No Redis needed** — we already write a `magic_links` row per request, so count
against it in SQLite:

```sql
SELECT COUNT(*) FROM magic_links
WHERE email = ? AND created_at > datetime('now', '-1 hour');
-- and the same keyed on request_ip
```

If the count is over the cap, skip sending but **still return 202** (no feedback
to caller). SQLite is plenty at our scale; Redis/Cloudflare rate-limiting would
only matter at much higher traffic or multiple backend servers.

## Frontend changes

### 1. New route `/verify`
- `?code=…` present → call existing `setAccessCode(code)`, then redirect into app.
  Reuses the exact storage `AccessUnlock` already reads via `getAccessCode()`.
- (Backend does the token→code redirect, so the frontend mainly handles `?code=`.)

### 2. `AccessUnlock` gets a second path (same component)
- Add an email field + "Zugang per E-Mail anfordern" → POSTs to
  `/api/auth/request-link` → shows "Check deine Mail."
- Keep the existing code box for manual/press codes.
- No change to `validateCode`, the `X-Access-Code` header, or storage.

## Token hygiene checklist

- Random token ≥ 256-bit (`secrets.token_urlsafe(32)`).
- Short expiry (~15 min).
- One-time use (`consumed_at`).
- HTTPS-only links.

## DSGVO / privacy

Storing emails now → obligations:
- Add a line to the Datenschutzerklärung about storing email for login.
- Support deletion on request: `DELETE FROM codes WHERE email=?` and
  `DELETE FROM magic_links WHERE email=?` is enough.

## Suggested commit order

1. Migration (`codes.email`) + `magic_links` table + DB helper methods.
2. `routers/magic.py` with both endpoints + rate limiting; email helper stubbed.
3. Wire up real transactional email provider + SPF/DKIM.
4. Frontend `/verify` route + `AccessUnlock` email path.
5. Datenschutzerklärung update.

## What this buys vs. costs

**Buys:** self-serve onboarding without Ulf in the loop; durable per-email
identity (revoke/re-issue, quotas already exist); clean seam for Stripe/tiers
later (attach to the email); no passwords to store/reset/leak.

**Costs / watch:** email deliverability (spam), DSGVO (stored emails),
rate-limiting the open endpoint, token hygiene.

**Rough size:** one migration, one table, one router (~2 endpoints), one email
helper, one frontend route + a few lines in `AccessUnlock`. ~a focused day,
most of it spent on email setup + deliverability testing, not logic — because
this extends the model we already have rather than replacing it.
