# LoanCentral Language Compliance Audit
Generated: 2026-06-09

## Purpose

Scan the project for terms that could imply financial guarantees, credit scoring, or endorsement of parties — language that would be inappropriate for a community record-keeping tool and potentially problematic from a legal/regulatory standpoint.

**No files were modified.** This is a report only.

---

## Terms Scanned

| Term | Risk |
|------|------|
| `guarantee` / `guaranteed` | Implies financial assurance — could suggest LoanCentral backs repayment |
| `safe lender` | Endorses a lender — LoanCentral does not vet lenders |
| `safe borrower` | Endorses a borrower |
| `trusted lender` | Implies LoanCentral vouches for a party |
| `approval score` | Implies a credit-style approval decision |
| `credit score` | Regulated term in many jurisdictions |
| `lender matching` | Implies a matching/referral service |
| `borrower matching` | Implies a matching/referral service |

---

## Findings

### `api/templates/dashboard_borrower.html`
**Line 42:**
```
Health score: based only on recorded repayment outcomes and currently late loans inside LoanCentral. It is not a credit score.
```
**Assessment:** ✅ Safe — the phrase "not a credit score" is a **disclaimer**, not a claim. This is correct language and should be kept.

---

### `api/templates/terms.html`
**Line 16:**
```
LoanCentral is a record-keeping tool for loan agreements made between users on Reddit. It does not lend money, hold funds, set interest rates, guarantee repayment, or act as a financial institution of any kind.
```
**Assessment:** ✅ Safe — the phrase "guarantee repayment" appears in a **denial** ("does not … guarantee repayment"). This is correct disclaimer language and should be kept.

**Line 39:**
```
LoanCentral does not guarantee any outcome from a dispute.
```
**Assessment:** ✅ Safe — again a denial/disclaimer. Correct usage.

---

### `VISION.md`
**Line 210:**
```
fine for community moderation. Do not present it as a credit score or use
```
**Assessment:** ✅ Safe — internal developer guidance explicitly prohibiting credit score framing. Keep as-is.

---

## Summary

| File | Occurrences | Action Required |
|------|-------------|-----------------|
| `api/templates/dashboard_borrower.html` | 1 | None — disclaimer language |
| `api/templates/terms.html` | 2 | None — denial/disclaimer language |
| `VISION.md` | 1 | None — internal guidance |

**No prohibited language found in any Python source files, bot commands, or user-facing messages outside of correct disclaimer contexts.**

---

## Recommendations

1. **Health score labeling** — The current label "Health Score" is acceptable. Do not rename it to "Credit Score", "Trustworthiness Score", or "Approval Score" in future UI work.

2. **Lender verification badge** — When the verified lender badge is displayed, use neutral language such as "Verified Lender (completed LoanCentral process)" rather than "Trusted Lender" or "Safe Lender".

3. **Future notifications** — If due-date reminder notifications are added, avoid phrases like "your lender has approved you" or "guaranteed funding". Use factual language: "Loan confirmed", "Payment due in 3 days", etc.

4. **Re-run this audit** before any major UI update or before going to production.
