# LoanCentral Next Feature Priorities

## Near-Term Dashboard

- Done: mobile polish pass on lender, borrower, profile, and mod pages with phone-width checks.
- Done: reminder queue foundation for overdue, due today, due in 1-3 days, and missing due dates.
- Done: borrower active-loan checklist includes due date, amount owed, payment method, thread, and acknowledge status.
- Done: user profile improvements with repayment timeline, active loans, unpaid history, and shared lender/borrower context.
- CSV export filters by status/date range.
- Done: mod activity feed tab with auto-refresh while open.
- Pending: mod activity filters for funded, repaid, unpaid, disputed, banned, and notes.

## Bot And Reddit API-Safe Work

- Done: scheduled reminder dry-run job foundation that batches reminder checks without Reddit calls.
- Done: Reddit action queue for reminders, flair sync, and mod-confirmed bans without live Reddit calls.
- Pending: live test-subreddit reminder delivery after test Reddit credentials are connected.
- Lender DM when a due date passes, with strict cooldowns.
- Bot confirmation comment after dashboard funding, only when a Reddit thread exists.
- Bot congratulations comment after full repayment, with opt-out/cooldown controls.
- `$extend` workflow for borrower extension requests and lender approval.
- Graceful handling for deleted/removed posts and missing authors in every command path.

## Trust And Moderation

- Done: dashboard lender verification application flow with mod approve/deny.
- Pending: Reddit flair update after lender verification approval, test-subreddit first.
- Done: approved lender verification queues a future Reddit flair sync action.
- Private mod notes and visible audit trail for every sensitive change.
- Ban log with issuer, reason, timestamp, and confirmation state.
- Manual loan correction flow with mandatory reason.
- Dispute workflow: borrower dispute, lender response, mod decision, audit note.

## Legal Guardrails

- Keep LoanCentral as a record-keeping and reputation tool.
- Do not show open borrower requests as a browsable lender marketplace.
- Keep funding decisions and negotiations on Reddit between users.
- Do not process payments or touch user funds.
- Keep public profile data factual: counts, statuses, dates, totals, verification state.

## Infrastructure

- Staging test subreddit and test Reddit accounts before production API use.
- Migration dry-run script for existing database upgrades.
- Deployment checklist with rollback steps.
- Structured app logs for API requests, bot actions, errors, and reminder jobs.
- Rate limits for dashboard APIs and Reddit action cooldowns.

## Live Reddit Switches

- Keep `REMINDER_REDDIT_ENABLED` unset/false until dry-run output is reviewed.
- Use a private test subreddit before any production Reddit comments or DMs.
- Keep auto-ban disabled until mod review flow is verified against test accounts.
- Keep Reddit flair sync disabled until OAuth/flair permissions are tested.
- Review queued Reddit actions in the mod dashboard before enabling any sender.
