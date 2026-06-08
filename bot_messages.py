import os


DASHBOARD_URL = os.getenv("DASHBOARD_URL", "https://loancentral.app")
DASHBOARD_FOOTER = (
    f"*Dashboard: [{DASHBOARD_URL}]({DASHBOARD_URL}) - sign in with Reddit "
    "to view history and manage loans.*"
)


def with_dashboard_link(message):
    """Append the dashboard footer to bot replies unless already present."""
    if DASHBOARD_URL in message:
        return message
    return f"{message}\n\n---\n{DASHBOARD_FOOTER}"
