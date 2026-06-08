# LoanCentral Mobile Preview

Use this only for offline demo/testing. It uses the local SQLite dev database
and fake users.

## Public Tunnel

Current quick tunnel:

```text
https://contained-gotten-learn-bryan.trycloudflare.com
```

Access key:

```text
8bMGmOJdBYiplAxajw
```

## Phone Links

Dev login:

```text
https://contained-gotten-learn-bryan.trycloudflare.com/auth/dev-login?access=8bMGmOJdBYiplAxajw
```

Direct lender demo:

```text
https://contained-gotten-learn-bryan.trycloudflare.com/auth/dev-login-as/testlender?access=8bMGmOJdBYiplAxajw
```

Direct borrower demo:

```text
https://contained-gotten-learn-bryan.trycloudflare.com/auth/dev-login-as/remote_weather186?access=8bMGmOJdBYiplAxajw
```

## What Was Verified

- Dev login fits phone width with no horizontal scroll.
- Lender dashboard fits phone width with no horizontal scroll.
- Borrower dashboard fits phone width with no horizontal scroll.
- Loan tables become stacked cards on mobile.
- Lender actions become tap-friendly button grids.
- The public route is blocked without the access key.

## Safety Notes

- Do not enter real Reddit API keys.
- Do not connect this tunnel to production database credentials.
- Stop the tunnel when done reviewing.
