"""The single definition of LoanCentral's loan and request lifecycles.

Before this module the rules were re-derived inline in every mutation:
``mark_repaid`` knew that refunded loans reject payments, ``mark_unpaid`` knew
that repaid loans cannot go unpaid, and ``update_request_status`` knew nothing at
all and would move a request from any status to any other — including
``funded -> open``, after which the request could be funded a second time and
the first loan was orphaned.

Both interfaces (Reddit commands and the dashboard) go through the services that
consult this table, so a status rule changes in exactly one place.

The transitions below were read out of the existing code, not invented — see
docs/reports/AUDIT_2026-09-21.md. This module deliberately has no imports from
the rest of the project: it is pure data plus three predicates, so it can be
consulted from services, routes, commands, and tests without a cycle.
"""

# ---------------------------------------------------------------------------
# Loans
# ---------------------------------------------------------------------------

LOAN_STATUSES = frozenset({
    "confirmed",
    "partially_repaid",
    "repaid",
    "unpaid",
    "refunded",
    "disputed",
})

#: Once a loan reaches one of these it is closed. Money has either come back in
#: full or been returned; nothing may move it again.
TERMINAL_LOAN_STATUSES = frozenset({"repaid", "refunded"})

#: current status -> statuses it may move to.
LOAN_TRANSITIONS = {
    "confirmed":        frozenset({"partially_repaid", "repaid", "unpaid",
                                   "refunded", "disputed"}),
    "partially_repaid": frozenset({"partially_repaid", "repaid", "unpaid",
                                   "refunded", "disputed"}),
    # A payment on an unpaid loan is how a defaulted borrower makes good.
    "unpaid":           frozenset({"partially_repaid", "repaid", "refunded",
                                   "disputed", "confirmed"}),
    "disputed":         frozenset({"partially_repaid", "repaid", "unpaid",
                                   "refunded"}),
    "repaid":           frozenset(),
    "refunded":         frozenset(),
}

#: Transitions no ordinary lender may make on their own. `unpaid -> confirmed`
#: clears a default, which is a reputation change, so it stays with mods
#: (/api/loans/<id>/clear-unpaid is already @require_mod_api).
MOD_ONLY_LOAN_TRANSITIONS = frozenset({("unpaid", "confirmed")})


# ---------------------------------------------------------------------------
# Loan requests
# ---------------------------------------------------------------------------

REQUEST_STATUSES = frozenset({
    "open",
    "funded",
    "expired",
    "cancelled",
    "removed",
    "duplicate",
    "denied_by_mod",
    "funded_backfill",
})

#: A funded request is settled: a loan record exists and points back at it.
#: Reopening one is what allowed the same request to be funded twice.
TERMINAL_REQUEST_STATUSES = frozenset({"funded", "funded_backfill", "removed"})

REQUEST_TRANSITIONS = {
    # funded_backfill reconciles an open request with a loan that already
    # exists (scripts backfill from the loans table).
    "open":          frozenset({"funded", "expired", "cancelled", "removed",
                                "duplicate", "denied_by_mod", "funded_backfill"}),
    # Wrongly flagged requests need a way back; a real duplicate gets removed.
    "duplicate":     frozenset({"open", "removed", "expired"}),
    "expired":       frozenset({"open", "removed", "cancelled"}),
    "cancelled":     frozenset({"open", "removed"}),
    "denied_by_mod": frozenset({"open", "removed"}),
    "funded":        frozenset(),
    "funded_backfill": frozenset(),
    "removed":       frozenset(),
}


class TransitionError(ValueError):
    """Raised when a caller attempts a transition the lifecycle forbids."""


# ---------------------------------------------------------------------------
# Predicates
# ---------------------------------------------------------------------------

def loan_transition_error(current, target, *, actor_role=None):
    """Return a user-facing reason the move is not allowed, or None if it is.

    `actor_role` is checked only for transitions in MOD_ONLY_LOAN_TRANSITIONS;
    pass "mod" or "admin" when the caller has already been authorised.
    """
    current = (current or "").strip().lower()
    target = (target or "").strip().lower()

    if target not in LOAN_STATUSES:
        return f"Unknown loan status: {target}."
    if current not in LOAN_STATUSES:
        # An unrecognised stored status is a data problem, not a user error —
        # refuse rather than guess which rules apply.
        return f"This loan has an unrecognised status ({current}) and cannot be changed."
    if current == target and target not in LOAN_TRANSITIONS[current]:
        return f"This loan is already {target}."
    if target not in LOAN_TRANSITIONS[current]:
        if current in TERMINAL_LOAN_STATUSES:
            return f"This loan is already {current} and can no longer be changed."
        return f"A {current} loan cannot be marked {target}."
    if (current, target) in MOD_ONLY_LOAN_TRANSITIONS and actor_role not in ("mod", "admin"):
        return "Only a moderator can make that change."
    return None


def request_transition_error(current, target, *, force=False):
    """Return a reason the request move is not allowed, or None if it is.

    `force` is the admin correction path for a request funded by mistake. It
    permits leaving an otherwise terminal status but never invents a target
    outside REQUEST_STATUSES. Callers must be admin and must audit the override.
    """
    current = (current or "").strip().lower()
    target = (target or "").strip().lower()

    if target not in REQUEST_STATUSES:
        return f"Invalid status: {target}"
    if current not in REQUEST_STATUSES:
        return f"This request has an unrecognised status ({current}) and cannot be changed."
    if current == target:
        return f"Request is already {target}."
    if target in REQUEST_TRANSITIONS[current]:
        return None
    if force:
        return None
    if current in TERMINAL_REQUEST_STATUSES:
        return (f"Request is already {current} and cannot be moved to {target}. "
                "An admin override is required to correct it.")
    return f"A {current} request cannot be moved to {target}."


def is_open_request(status):
    """True when a request is still awaiting a funding decision."""
    return (status or "").strip().lower() == "open"
