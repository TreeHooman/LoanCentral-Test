# Error Logging — Sprint 7
Date: 2026-06-09

## Overview
A `log_request_error(exc, *, extra="")` helper was added to `api/app.py`. It is the single place where request-context errors are structured and emitted, ensuring consistent fields across all error paths.

## Helper signature
```python
def log_request_error(exc: Exception, *, extra: str = ""):
```
Called from the `@app.errorhandler(500)` handler and the new `@app.errorhandler(Exception)` catch-all.

## Fields captured per error
| Field | Source | Notes |
|---|---|---|
| timestamp | logging framework | ISO 8601 via `basicConfig` format |
| method | `request.method` | GET, POST, etc. |
| path | `request.path` | Never includes query params |
| user | `session.get("username")` | "anonymous" if not logged in |
| role | `session.get("role")` | "-" if not set |
| remote_addr | `request.remote_addr` | Client IP |
| exc_type | `type(exc).__name__` | Exception class name |
| message | `str(exc)` | Exception message |
| stack trace | `exc_info=True` | Full traceback in log file |
| extra | optional kwarg | "unhandled" for catch-all handler |

## What end users see
Only the generic message from `error.html` or `{"error": "Internal server error"}` — no stack traces, no exception messages, no file paths. Internal detail stays in the server log only.

## Log format (production)
```
2026-06-09 12:34:56,789 ERROR LoanCentral.api request_error method=POST path=/api/loans/create user=lender1 role=lender remote=1.2.3.4 exc=KeyError msg='amount' 
Traceback (most recent call last):
  ...
```

## Handlers that use it
- `@app.errorhandler(500)` — Flask-caught server errors
- `@app.errorhandler(Exception)` — unhandled exceptions that escape route handlers

## How to add to a new route
Call `log_request_error(e)` from any `except Exception as e:` block in a route before returning an error response. Do NOT call it in service-layer functions — those use the `services` logger directly.

## Retention
Logs go to stdout/stderr on Render and are retained according to Render's log retention policy (currently 7 days on free tier). For longer retention, pipe to an external log aggregator (Papertrail, Logtail, etc.) via the Render log drain.
