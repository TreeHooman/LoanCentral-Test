-- LoanCentral Database Schema
-- This file contains the complete database schema for the LoanCentral bot

-- Create loans table to store information about individual loans
CREATE TABLE IF NOT EXISTS loans (
    id SERIAL PRIMARY KEY,
    loan_id TEXT UNIQUE,
    lender TEXT NOT NULL,
    borrower TEXT NOT NULL,
    amount NUMERIC NOT NULL,
    currency TEXT NOT NULL,
    date_created TIMESTAMP NOT NULL,
    original_thread TEXT NOT NULL,
    status TEXT DEFAULT 'active',
    amount_repaid NUMERIC DEFAULT 0,
    last_updated TIMESTAMP
);

-- Create users table to store aggregate statistics about users
CREATE TABLE IF NOT EXISTS users (
    username TEXT PRIMARY KEY,
    loans_as_borrower INTEGER DEFAULT 0,
    loans_as_lender INTEGER DEFAULT 0,
    amount_borrowed NUMERIC DEFAULT 0,
    amount_lent NUMERIC DEFAULT 0,
    amount_repaid NUMERIC DEFAULT 0,
    unpaid_loans INTEGER DEFAULT 0,
    unpaid_amount NUMERIC DEFAULT 0,
    last_updated TIMESTAMP
);

-- User roles table for dashboard access control
CREATE TABLE IF NOT EXISTS user_roles (
    username TEXT PRIMARY KEY,
    role TEXT NOT NULL DEFAULT 'borrower',       -- 'mod', 'lender', 'borrower'
    subscription_status TEXT NOT NULL DEFAULT 'free',  -- 'free', 'paid'
    created_at TIMESTAMP DEFAULT NOW(),
    last_login TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_user_roles_role ON user_roles(role);

-- Role requests table (borrowers requesting lender access)
CREATE TABLE IF NOT EXISTS role_requests (
    username TEXT PRIMARY KEY,
    requested_role TEXT NOT NULL DEFAULT 'lender',
    reason TEXT,
    status TEXT NOT NULL DEFAULT 'pending',  -- 'pending', 'approved', 'denied'
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_role_requests_status ON role_requests(status);

-- Password login support (no Reddit OAuth required)
ALTER TABLE user_roles ADD COLUMN IF NOT EXISTS password_hash TEXT;

-- SMS reminders
ALTER TABLE user_roles ADD COLUMN IF NOT EXISTS phone_number TEXT;
ALTER TABLE loans ADD COLUMN IF NOT EXISTS last_reminder_sent TIMESTAMP;
CREATE INDEX IF NOT EXISTS idx_loans_reminder ON loans(last_reminder_sent);

-- Due dates on loans
ALTER TABLE loans ADD COLUMN IF NOT EXISTS due_date TIMESTAMP;
CREATE INDEX IF NOT EXISTS idx_loans_due_date ON loans(due_date);

-- Lender availability flag
ALTER TABLE user_roles ADD COLUMN IF NOT EXISTS available BOOLEAN DEFAULT true;

-- Audit log: tracks all significant mod/lender actions
CREATE TABLE IF NOT EXISTS audit_log (
    id SERIAL PRIMARY KEY,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    target TEXT,
    details TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_audit_log_created_at ON audit_log(created_at DESC);

-- Loan applications: borrowers post requests, lenders claim them
CREATE TABLE IF NOT EXISTS loan_applications (
    id SERIAL PRIMARY KEY,
    borrower TEXT NOT NULL,
    amount NUMERIC NOT NULL,
    currency TEXT NOT NULL DEFAULT 'USD',
    reason TEXT,
    repayment_plan TEXT,
    status TEXT NOT NULL DEFAULT 'open',  -- 'open', 'claimed', 'funded', 'cancelled'
    lender TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_loan_apps_borrower ON loan_applications(borrower);
CREATE INDEX IF NOT EXISTS idx_loan_apps_status ON loan_applications(status);

-- Migration: add date_repaid column (safe to re-run)
ALTER TABLE loans ADD COLUMN IF NOT EXISTS date_repaid TIMESTAMP;
CREATE INDEX IF NOT EXISTS idx_loans_date_repaid ON loans(date_repaid);

-- Mod notes on individual loans
ALTER TABLE loans ADD COLUMN IF NOT EXISTS notes TEXT;

-- Dispute system: borrowers can dispute an unpaid mark
CREATE TABLE IF NOT EXISTS disputes (
    id SERIAL PRIMARY KEY,
    loan_id INTEGER NOT NULL,
    borrower TEXT NOT NULL,
    reason TEXT,
    status TEXT NOT NULL DEFAULT 'open',   -- 'open', 'resolved', 'dismissed'
    resolution TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    resolved_at TIMESTAMP,
    resolved_by TEXT
);
CREATE INDEX IF NOT EXISTS idx_disputes_status  ON disputes(status);
CREATE INDEX IF NOT EXISTS idx_disputes_loan_id ON disputes(loan_id);

-- Create indexes for better query performance
CREATE INDEX IF NOT EXISTS idx_loans_lender ON loans(lender);
CREATE INDEX IF NOT EXISTS idx_loans_borrower ON loans(borrower);
CREATE INDEX IF NOT EXISTS idx_loans_status ON loans(status);
CREATE INDEX IF NOT EXISTS idx_loans_date_created ON loans(date_created);