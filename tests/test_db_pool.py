"""Postgres connection reuse (utils.get_db_connection).

Each dashboard page used to open a dozen fresh connections to Neon, a TLS +
auth handshake each, which made sign-in and every page slow. close() now hands
the connection back for the next caller.
"""

import os
import unittest
from unittest.mock import patch

import utils


class FakeRaw:
    """Just enough of a psycopg2 connection."""
    opened = 0

    def __init__(self):
        FakeRaw.opened += 1
        self.closed = 0
        self.rollbacks = 0
        self.status = 0            # TRANSACTION_STATUS_IDLE

    def get_transaction_status(self):
        return self.status

    def rollback(self):
        self.rollbacks += 1
        self.status = 0

    def close(self):
        self.closed = 1

    def cursor(self):
        return "cursor"


class PoolTests(unittest.TestCase):
    def setUp(self):
        FakeRaw.opened = 0
        utils._pool.clear()
        env = patch.dict(os.environ, {"DB_BACKEND": "postgres", "DB_POOL": "1"})
        env.start()
        self.addCleanup(env.stop)
        connect = patch.object(utils, "_connect_postgres", side_effect=FakeRaw)
        connect.start()
        self.addCleanup(connect.stop)
        reaper = patch.object(utils, "_start_reaper", lambda: None)
        reaper.start()
        self.addCleanup(reaper.stop)
        self.addCleanup(utils._pool.clear)

    def test_a_closed_connection_is_reused(self):
        first = utils.get_db_connection()
        raw = first._raw
        first.close()
        second = utils.get_db_connection()
        self.assertIs(second._raw, raw)
        self.assertEqual(FakeRaw.opened, 1)
        self.assertEqual(second.cursor(), "cursor")   # calls pass through

    def test_close_discards_uncommitted_work_like_a_real_close(self):
        conn = utils.get_db_connection()
        conn._raw.status = 2       # INTRANS: something was written, not committed
        raw = conn._raw
        conn.close()
        self.assertEqual(raw.rollbacks, 1)

    def test_a_closed_wrapper_reports_closed_and_closing_twice_is_harmless(self):
        conn = utils.get_db_connection()
        conn.close()
        conn.close()
        self.assertTrue(conn.closed)
        self.assertEqual(len(utils._pool), 1)

    def test_idle_connections_are_not_reused(self):
        conn = utils.get_db_connection()
        raw = conn._raw
        conn.close()
        utils._pool[0] = (raw, utils._pool[0][1] - utils._POOL_MAX_IDLE - 1)
        again = utils.get_db_connection()
        self.assertIsNot(again._raw, raw)
        self.assertTrue(raw.closed)

    def test_dead_connections_are_not_reused(self):
        conn = utils.get_db_connection()
        raw = conn._raw
        conn.close()
        raw.closed = 1
        self.assertIsNot(utils.get_db_connection()._raw, raw)

    def test_pool_is_bounded(self):
        conns = [utils.get_db_connection() for _ in range(utils._POOL_SIZE + 3)]
        for c in conns:
            c.close()
        self.assertEqual(len(utils._pool), utils._POOL_SIZE)
        self.assertEqual(sum(1 for c in conns if c._raw.closed), 3)

    def test_unpooled_connections_really_close(self):
        conn = utils.get_db_connection(pooled=False)
        self.assertIsInstance(conn, FakeRaw)
        conn.close()
        self.assertEqual(utils._pool, [])

    def test_can_be_switched_off(self):
        with patch.dict(os.environ, {"DB_POOL": "0"}):
            self.assertIsInstance(utils.get_db_connection(), FakeRaw)

    def test_sync_lock_uses_its_own_connection(self):
        """The advisory lock is released by closing the session, so it must
        never sit in the pool."""
        import reddit_sync
        with patch("services._get_db", side_effect=lambda: utils.get_db_connection()), \
             patch.object(utils, "get_db_connection", wraps=utils.get_db_connection) as get:
            class Cur:
                def execute(self, *a): pass
                def fetchone(self): return (True,)
                def close(self): pass
            with patch.object(FakeRaw, "cursor", lambda self: Cur(), create=True):
                conn, acquired = reddit_sync._acquire_live_lock()
        self.assertTrue(acquired)
        self.assertIsInstance(conn, FakeRaw)
        get.assert_any_call(pooled=False)


if __name__ == "__main__":
    unittest.main()
