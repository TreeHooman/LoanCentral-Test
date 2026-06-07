import os

DASHBOARD_URL  = os.getenv("DASHBOARD_URL", "http://localhost:5000")
LENDER_FLAIR   = os.getenv("LENDER_FLAIR", "Verified Lender")   # flair text required to use $loan
SUBREDDIT_NAME = os.getenv("SUBREDDITS", "").split(",")[0].strip()  # primary sub name for links
