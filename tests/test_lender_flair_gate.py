"""Lender flair = lender access (owner decision 2026-09-23)."""

import os
import unittest
from unittest.mock import patch

from commands import lender_gate
from tests.support.dbcase import RealDBTestCase


class _Author:
    def __init__(self, name):
        self.name = name


class _Subreddit:
    display_name = "LoanCentral"

    def __init__(self, rows=None, error=None):
        self._rows, self._error = rows or [], error

    def flair(self, redditor=None):
        if self._error:
            raise self._error
        return self._rows


class _Comment:
    """A PRAW-like comment. Pass flair=... to include inline author flair."""

    def __init__(self, author, subreddit=None, **flair):
        self.author = _Author(author)
        self.subreddit = subreddit or _Subreddit()
        self.replies = []
        for key, value in flair.items():
            setattr(self, key, value)

    def reply(self, body):
        self.replies.append(body)


class FlairMatchingTests(unittest.TestCase):
    def check(self, text, template=None):
        return lender_gate._flair_matches(text, template)

    def test_exact_text_matches_ignoring_case_and_spacing(self):
        self.assertTrue(self.check("Verified Lender"))
        self.assertTrue(self.check("  verified   LENDER "))

    def test_look_alikes_do_not_match(self):
        # The old check was a substring test, so "Unverified Lender" passed.
        for text in ("Unverified Lender", "Verified Lender (pending)", "Lender", "", None):
            self.assertFalse(self.check(text), text)

    def test_emoji_codes_are_ignored(self):
        self.assertTrue(self.check(":star: Verified Lender"))

    def test_the_accepted_texts_are_configurable(self):
        with patch.dict(os.environ, {"LENDER_FLAIR_TEXT": "Lender, Trusted Lender"}):
            self.assertTrue(self.check("lender"))
            self.assertTrue(self.check("Trusted Lender"))
            self.assertFalse(self.check("Verified Lender"))

    def test_template_mode_ignores_the_text(self):
        with patch.dict(os.environ, {"LENDER_FLAIR_TEMPLATE_ID": "abc-123"}):
            self.assertTrue(self.check("anything", "abc-123"))
            self.assertFalse(self.check("Verified Lender", "user-edited"))


class FlairGateTests(RealDBTestCase):
    def verified(self, username):
        rows = self.query("SELECT verified_lender, verified_lender_by, perm_version "
                          "FROM user_roles WHERE username = %s", (username,))
        return rows[0] if rows else None

    def test_a_flaired_newcomer_is_let_in_and_recorded_as_verified(self):
        comment = _Comment("NewLender", author_flair_text="Verified Lender")
        self.assertTrue(lender_gate.require_verified_lender(comment))
        row = self.verified("newlender")
        self.assertTrue(row[0])
        self.assertEqual(row[1], lender_gate.FLAIR_GRANTOR)
        audit = self.query("SELECT actor_username, action_type FROM audit_logs "
                           "WHERE target_id = %s", ("newlender",))
        self.assertEqual(audit, [(lender_gate.FLAIR_GRANTOR, "verified_lender_granted")])
        self.assertEqual(comment.replies, [])

    def test_an_already_verified_lender_is_not_re_granted(self):
        comment = _Comment("NewLender", author_flair_text="Verified Lender")
        lender_gate.require_verified_lender(comment)
        version = self.verified("newlender")[2]
        lender_gate.require_verified_lender(comment)
        # A second grant would bump perm_version and sign them out of the dashboard.
        self.assertEqual(self.verified("newlender")[2], version)

    def test_no_flair_means_silently_ignored(self):
        self.make_user("dbonly", role="lender", verified_lender=True)
        comment = _Comment("dbonly", author_flair_text=None)
        self.assertFalse(lender_gate.require_verified_lender(comment))
        self.assertEqual(comment.replies, [])

    def test_unreadable_flair_falls_back_to_the_verification_record(self):
        self.make_user("known", role="lender", verified_lender=True)
        broken = _Subreddit(error=RuntimeError("403 Forbidden"))
        self.assertTrue(lender_gate.require_verified_lender(_Comment("known", broken)))
        self.assertFalse(lender_gate.require_verified_lender(_Comment("stranger", broken)))

    def test_the_subreddit_lookup_is_used_when_the_comment_has_no_flair_data(self):
        subreddit = _Subreddit(rows=[{"flair_text": "Verified Lender"}])
        self.assertTrue(lender_gate.require_verified_lender(_Comment("viaapi", subreddit)))
