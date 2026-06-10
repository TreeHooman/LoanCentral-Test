# Backup & Restore — LoanCentral
Date: 2026-06-09

## SQLite (dev)

Database file: `data/loancentral_dev.sqlite3`

### Backup
```powershell
# Consistent snapshot even while the app is running
sqlite3 "data\loancentral_dev.sqlite3" ".backup 'backups\loancentral_dev_$(Get-Date -Format yyyyMMdd_HHmmss).sqlite3'"
# Or, with the app stopped, a plain copy works:
Copy-Item data\loancentral_dev.sqlite3 backups\loancentral_dev_YYYYMMDD.sqlite3
```

### Restore
```powershell
Copy-Item backups\loancentral_dev_YYYYMMDD.sqlite3 data\loancentral_dev.sqlite3 -Force
```

### Verify
```powershell
sqlite3 data\loancentral_dev.sqlite3 "PRAGMA integrity_check; SELECT COUNT(*) FROM loans; SELECT COUNT(*) FROM user_roles;"
```

## PostgreSQL (prod — Render, Oregon)

Connection values come from `.env` (`DB_HOST`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`). Never hardcode them in scripts or commit them.

### Backup (pg_dump, custom format)
```powershell
$env:PGPASSWORD = "<DB_PASSWORD from .env>"
pg_dump -h <DB_HOST> -U <DB_USER> -d <DB_NAME> -Fc -f "backups\loancentral_prod_$(Get-Date -Format yyyyMMdd_HHmmss).dump"
Remove-Item Env:PGPASSWORD
```
Render also takes automatic daily snapshots — the manual dump is in addition, not a replacement.

### Restore
```powershell
$env:PGPASSWORD = "<DB_PASSWORD>"
# Into an empty database (typical disaster recovery):
pg_restore -h <DB_HOST> -U <DB_USER> -d <DB_NAME> --clean --if-exists --no-owner backups\loancentral_prod_YYYYMMDD.dump
Remove-Item Env:PGPASSWORD
```

### Verify after restore
```powershell
psql -h <DB_HOST> -U <DB_USER> -d <DB_NAME> -c "
SELECT 'loans' t, COUNT(*) FROM loans
UNION ALL SELECT 'users', COUNT(*) FROM users
UNION ALL SELECT 'user_roles', COUNT(*) FROM user_roles
UNION ALL SELECT 'audit_logs', COUNT(*) FROM audit_logs
UNION ALL SELECT 'loan_events', COUNT(*) FROM loan_events
UNION ALL SELECT 'notifications', COUNT(*) FROM notifications
UNION ALL SELECT 'verification_applications', COUNT(*) FROM verification_applications;"
```
Compare counts with the pre-backup numbers, then load the dashboard and spot-check a loan timeline and the audit log.

## Secrets hygiene — never commit
- `.env` (DB credentials, API_KEY, SECRET_KEY, Reddit credentials)
- `backups/` directory and any `.dump` / `.sqlite3` files (contain user data)
- `uploads/` (loan attachments)

Add to `.gitignore` if not already present.

## Checklist
- [ ] Backup before any schema migration
- [ ] Backup before each deployment
- [ ] Backup after a successful deployment (known-good snapshot)
- [ ] Test a restore into a scratch database monthly
- [ ] Confirm Render automatic snapshots are enabled and retained
