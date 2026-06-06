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

-- Create indexes for better query performance
CREATE INDEX IF NOT EXISTS idx_loans_lender ON loans(lender);
CREATE INDEX IF NOT EXISTS idx_loans_borrower ON loans(borrower);
CREATE INDEX IF NOT EXISTS idx_loans_status ON loans(status);
CREATE INDEX IF NOT EXISTS idx_loans_date_created ON loans(date_created);