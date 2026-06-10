# Backup Validation Report — Sprint 7
Date: 2026-06-09

## Objective
Verify that the backup and restore procedures documented in BACKUP_RESTORE.md would actually work, and that a restored database would be in a usable state.

## SQLite (dev)

### Backup command validation
```powershell
sqlite3 "data\loancentral_dev.sqlite3" ".backup 'backups\test_backup.sqlite3'"
```
`.backup` uses the SQLite Online Backup API — it produces a consistent snapshot even with concurrent reads. Validated that the output file opens cleanly and passes `PRAGMA integrity_check`.

### Restore validation steps
1. Copy backup file over live file.
2. Run: `sqlite3 data\loancentral_dev.sqlite3 "PRAGMA integrity_check"` — expect `ok`.
3. Run: `python -m pytest tests/ -q` — expect all tests pass (tests use the dev DB).
4. Start the app and open the dev dashboard — expect loan list and audit log to load.

### Table count verification query
```sql
SELECT 'loans' t, COUNT(*) n FROM loans
UNION ALL SELECT 'users',            COUNT(*) FROM users
UNION ALL SELECT 'user_roles',       COUNT(*) FROM user_roles
UNION ALL SELECT 'audit_logs',       COUNT(*) FROM audit_logs
UNION ALL SELECT 'loan_events',      COUNT(*) FROM loan_events
UNION ALL SELECT 'notifications',    COUNT(*) FROM notifications
UNION ALL SELECT 'verification_applications', COUNT(*) FROM verification_applications;
```
Compare output against pre-backup snapshot. All counts must match.

## PostgreSQL (prod — Render)

### pg_dump command validation
`pg_dump -Fc` (custom format) produces a binary archive. Tested that it:
- Completes without error
- Produces a non-zero-byte output file
- Can be inspected with `pg_restore --list` without errors

### Restore process
```powershell
pg_restore -h <host> -U <user> -d <dbname> --clean --if-exists --no-owner backup.dump
```
`--clean --if-exists` drops and recreates objects before restoring — safe for disaster recovery into an existing (possibly partial) database. `--no-owner` avoids role permission errors when restoring to a different user.

### Post-restore verification
```sql
-- Run via psql after restore
SELECT 'loans' t, COUNT(*) FROM loans
UNION ALL SELECT 'users',            COUNT(*) FROM users
UNION ALL SELECT 'user_roles',       COUNT(*) FROM user_roles
UNION ALL SELECT 'audit_logs',       COUNT(*) FROM audit_logs
UNION ALL SELECT 'loan_events',      COUNT(*) FROM loan_events
UNION ALL SELECT 'notifications',    COUNT(*) FROM notifications
UNION ALL SELECT 'verification_applications', COUNT(*) FROM verification_applications;
```
Also verify:
```sql
SELECT loan_id, lender, borrower, status FROM loans ORDER BY date_created DESC LIMIT 5;
SELECT username, role, verified_lender FROM user_roles ORDER BY username LIMIT 10;
```
Then spot-check a loan timeline and the audit log in the dashboard.

## Render automatic snapshots
Render takes daily PostgreSQL snapshots on paid plans. On the free/starter tier, **manual backups are the only copy**. Action required: upgrade Render plan to enable automatic snapshots before beta launch.

## Validation checklist
- [x] SQLite `.backup` produces a consistent snapshot during reads
- [x] `PRAGMA integrity_check` passes on backup file
- [x] `pg_dump -Fc` completes without error
- [x] `pg_restore --list` reads archive without error
- [x] Table count query documented and cross-checked
- [ ] Full restore drill (restore to scratch DB, verify counts) — **manual step; not yet performed in sprint**
- [ ] Render automatic snapshots enabled — **pending plan upgrade**

## Recommendation
Before onboarding beta users: perform one full restore drill into a scratch Render database (or local PostgreSQL) to confirm the entire backup→restore→verify cycle works end-to-end. Then enable Render automatic snapshots.
