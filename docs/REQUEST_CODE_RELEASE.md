# Request-Code Funding Release Plan

Updated: 2026-09-08. Status: local feature complete for the demonstrated flow;
not ready for production upload. No production deployment changes made.

Preservation constraint: development stays local. Uploads, live Reddit testing,
and changes to the legacy installation are distinct release steps, not side
effects of development. No account or API access can be guaranteed ban-proof.
The existing account's age and previous subreddit access do not provide such
a guarantee. Preserve its registration and credentials, and establish the
permitted use and combined request budget before starting shared-account tests.

## Release Scope

Request reply -> code or dashboard link -> signed-in lender review -> recorded
funding -> linked loan and repayment tracking. Preserve the existing Reddit
commands and legacy loan identifiers. See [feature details](REQUEST_CODE_FLOW.md).

Owner decisions: the legacy bot is running on another computer; this machine
is separate. The lender alone records and updates loans, with no borrower
confirmation step. Recruit new lenders only after the bot release and rebrand
are ready; pilot with existing participants.

The last code run passed 620 Python tests. Playwright checks passed at desktop
and mobile sizes, including lookup, required confirmation, stale-code rejection,
and recording a fake loan. These were SQLite/offline checks, not Reddit or
production PostgreSQL certification.

## Resolve Before Live Testing

| Item | Evidence / next action |
| --- | --- |
| Lender-only workflow | Owner confirmed no borrower confirmation step. Preserve the demo's lender recording action, and prepare matching pinned instructions for release. Do not introduce borrower approval as a dependency. |
| Real title formats | Offline probes miss the principal in a bare `$40` title and repayment in `Payback` / `[REPAY]` formats. Add representative, anonymized fixtures, explicit year tests, ambiguous-date handling, and missing-field review. |
| Prearranged requests | `[PRE]` gets a history reply today, but request-code creation currently runs only for `[REQ]`. Define whether prearranged posts also get a code and test that path. |
| Legacy process | Owner confirmed it runs on another computer. Capture its running revision, Python/dependency versions, startup command, restart policy, and database destination. The checked-in Render manifest describes the dashboard, not that Reddit worker. |
| EU isolation | Confirm the exact EU name and that no real lending needs its current bot support. Prepare a test-only database and disjoint subreddit lists. |
| Startup guard | Reject a production database or main subreddit in the test launcher; resolve inherited `DATABASE_URL` before startup. Set configuration before importing `utils` or `main`. |
| Dashboard identity | Test actual lender/borrower login and linked Reddit identities. The demo bypass is not production login; the existing OAuth implementation is not evidence of an approved working integration. |
| Source data | Identify the authoritative live database; investigate the seven historical overpayment flags without automatically changing records. |

Procedure source: [pinned borrower instructions](https://www.reddit.com/r/LoanCentral/comments/1r1dz6f/borrower_loan_procedure/).
The pinned post predates the owner-confirmed lender-only dashboard flow. Its
wording should be updated together with the release, not silently changed now.

## Test Sequence

1. Preserve lender-only recording and fill the parser/`[PRE]` gaps.
2. Run command, service, and browser regressions against fake data.
3. Repeat transaction tests against isolated PostgreSQL: two lenders funding
   simultaneously, public ID collision, failed request link, failed audit insert,
   and connection failure. Confirm no orphan loans or duplicate borrower totals.
4. On the staging dashboard, test genuine login, revocation, linked identities,
   borrower visibility, and denied actions by unrelated users.
5. Run a small EU pilot with clearly labeled fake posts: request reply and code,
   dashboard lookup, lender-recorded funding, partial/full repayment, refund, unpaid,
   duplicate attempt, restart, and recovery after a connection interruption.
6. Verify that only the intended process responds in each subreddit and that
   staging actions never alter production records. Inspect shared API usage.

The same Reddit account shares rate limits and account-level exposure. Separate
databases and processes do not remove that dependency.

## Upload And Cutover

After the above evidence is recorded:

1. Record the tested candidate commit and the currently deployed legacy commit.
   Preserve a runnable legacy checkout and its configuration references, without
   putting secrets in Git.
   Prepare a separate candidate directory on the other computer. Copy only
   versioned application files, not this machine's `.env`, demo databases,
   `.public-dashboard-token`, uploads, logs, or virtual environment. Install
   dependencies in the candidate's own environment and leave the running
   legacy directory in place until the planned switch.
2. Make a fresh production backup and successfully restore it into an isolated
   destination. Check loan/request counts and sample histories after restore.
3. Review only required schema changes against the restored copy and verify
   compatibility with the legacy process. Avoid destructive migrations.
4. Check which branch each service deploys and whether pushes trigger deployment.
   A push to a tracked branch may be the deployment itself.
5. Deploy the tested dashboard configuration with production authentication,
   HTTPS, correct dashboard URL, and correct database. Never deploy the demo launcher.
6. Stop the legacy Reddit worker only at the planned cutover; start the tested
   worker on the intended production subreddit. Do not overlap their monitors.
7. Verify reads and process the next agreed pilot action. Monitor errors,
   duplicate replies, queue state, and database consistency.

## Rollback

Stop the new worker first and preserve its logs. Restart the captured legacy
revision only after confirming its schema compatibility and recording which
events happened during cutover. Preserve production records created after the
backup. A code rollback does not require overwriting the live database with an
older backup; reconcile data separately if necessary.

## Deferred Features

Dashboard-funded confirmation comments and automatic reminder delivery still
need an outbound queue sender. They are not part of the demonstrated request
lookup flow. Keep live bans, DMs, and flair synchronization disabled during the
initial pilot unless included in a separately tested release scope.
