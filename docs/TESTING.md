# Testing Guide

## Current Safety Level

The current tests are offline tests. They do not connect to Reddit, do not use Reddit API credentials, and do not connect to the production database.

The tests replace `utils.get_db_connection` with fake in-memory objects and capture bot replies locally.

## Run Offline Tests

From the project folder:

```powershell
python -m unittest discover -s tests
```

If Python is not installed or not on PATH, install Python first or rebuild the project virtual environment.

## Do Not Use Yet

Do not run these against:

- the production Reddit bot account
- production Reddit credentials
- the production database
- live subreddit streams

## First Regression Coverage

The first tests cover `$paid_with_id`:

- lender can record partial payment by database ID
- lender can record full payment by public loan ID
- wrong lender gets a clear authorization error
- missing loan gets a clear not-found error
- currency mismatch does not update the loan

