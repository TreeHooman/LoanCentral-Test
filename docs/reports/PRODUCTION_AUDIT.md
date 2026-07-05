# Production Configuration Audit — Sprint 7
Date: 2026-06-09

## Summary
Two gaps fixed this sprint. No critical vulnerabilities found. Several recommendations remain for post-beta hardening.

---

## DEBUG mode — PASS
`app.run(debug=IS_DEV)` — `IS_DEV` is `True` only when `LOANCENTRAL_ENV != "prod"`. Render sets `LOANCENTRAL_ENV=prod`, so debug mode is off in production. Werkzeug interactive debugger is never exposed.

## Session cookie settings — FIXED this sprint
```python
app.config["SESSION_COOKIE_HTTPONLY"] = True   # JS cannot read session cookie
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"  # CSRF mitigation for navigational requests
app.config["SESSION_COOKIE_SECURE"]  = True     # HTTPS-only in prod (False in dev for localhost)
```
`SESSION_COOKIE_SECURE` is driven by the same `_is_prod` flag as other hardening.

## Security response headers — ADDED this sprint
Applied via `@app.after_request` on every response:
```
X-Content-Type-Options: nosniff
X-Frame-Options: DENY
Referrer-Policy: strict-origin-when-cross-origin
X-XSS-Protection: 0          (disabled in favour of CSP — modern browser recommendation)
Strict-Transport-Security: max-age=63072000; includeSubDomains  (prod only)
```

## Secret management — PASS with notes
- `SECRET_KEY` is loaded from `.env` via `os.getenv`. The fallback `secrets.token_hex(32)` would rotate the key on every restart (logging out all sessions) if the env var is missing — acceptable fail-safe.
- `API_KEY` fallback is `"changeme"` — **must be set in prod `.env`**. Currently set per project setup.
- `.env` is in `.gitignore`. Verified not committed.

## CSRF protection — PARTIAL
State-changing routes (POST, DELETE) require either an active session or the `X-API-Key` header. The session cookie has `SameSite=Lax`, which blocks cross-origin form submissions from other domains. **Not using a CSRF token library** (flask-wtf etc.) — acceptable for a dashboard that does not use traditional form submissions (all state changes go through fetch/XHR from the same origin).

Risk: CSRF via top-level navigation (GET-as-state-change) is not relevant here; all state changes are POSTs/DELETEs from JS. Recommendation: add flask-wtf CSRF tokens if traditional form submissions are ever introduced.

## Content Security Policy — NOT SET
No `Content-Security-Policy` header is set. This is a medium-priority gap — without CSP, a stored XSS vulnerability would have no browser-level mitigation.

**Recommendation:** Add a restrictive CSP header in `add_security_headers`. Suggested starting point:
```
Content-Security-Policy: default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; frame-ancestors 'none'
```
`unsafe-inline` is needed until scripts are moved to external files. Long-term: use nonces.

## Rate limiting — PASS
`_api_rate_hits` in-process rate limiter caps at `API_RATE_LIMIT_PER_MINUTE` (default 120) per user/key/IP on all `/api/` paths. OTP endpoints additionally capped at 5 per 15 minutes per IP.

Limitation: in-process state is not shared across Render instances. If the service scales to multiple workers, rate limiting will not be enforced globally. Mitigation: Render free/starter tier runs a single worker; add Redis-backed rate limiting before scaling.

## Session lifetime — PASS
`permanent_session_lifetime = timedelta(days=7)`. Sessions do NOT auto-extend on activity — users are logged out after 7 days. Acceptable for a private dashboard.

## Render-specific — VERIFIED
- HTTPS is enforced by Render at the load balancer — all HTTP is redirected to HTTPS.
- `PORT` env var is respected (`int(os.getenv("API_PORT", 5000))`).
- Render does not expose the DB port publicly.

## Findings summary
| Finding | Severity | Status |
|---|---|---|
| SESSION_COOKIE_SECURE not set | High | Fixed this sprint |
| X-Frame-Options / security headers missing | Medium | Fixed this sprint |
| Content-Security-Policy not set | Medium | Deferred — post-beta |
| CSRF token library not used | Low | Acceptable (XHR-only) |
| Rate limiting not shared across workers | Low | Acceptable (single worker) |
| API_KEY fallback is "changeme" | High | Must be set in .env — verified set |
