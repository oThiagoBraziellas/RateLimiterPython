import math
import threading
import unittest

from rate_limiter import FakeClock, KeyedLimiter, SlidingWindowLog, TokenBucket


class TokenBucketTests(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()

    def test_allows_burst_up_to_capacity_then_denies(self):
        b = TokenBucket(3, 1, clock=self.clock)
        self.assertEqual([bool(b.allow()) for _ in range(4)], [True, True, True, False])

    def test_refills_over_time(self):
        b = TokenBucket(2, 1, clock=self.clock)
        b.allow()
        b.allow()
        self.assertFalse(b.allow())
        self.clock.advance(1)
        self.assertTrue(b.allow())
        self.assertFalse(b.allow())

    def test_refill_is_capped_at_capacity(self):
        b = TokenBucket(2, 10, clock=self.clock)
        self.clock.advance(1000)
        self.assertEqual(b.tokens, 2)

    def test_fractional_refill(self):
        b = TokenBucket(1, 2, clock=self.clock)  # 2 tokens/s
        b.allow()
        self.clock.advance(0.25)
        self.assertFalse(b.allow())
        self.clock.advance(0.25)
        self.assertTrue(b.allow())

    def test_retry_after(self):
        b = TokenBucket(2, 4, clock=self.clock)
        b.allow(2)
        d = b.allow(1)
        self.assertFalse(d.allowed)
        self.assertAlmostEqual(d.retry_after, 0.25)
        self.clock.advance(d.retry_after)
        self.assertTrue(b.allow())

    def test_cost_larger_than_capacity_never_succeeds(self):
        b = TokenBucket(2, 1, clock=self.clock)
        d = b.allow(3)
        self.assertFalse(d.allowed)
        self.assertTrue(math.isinf(d.retry_after))

    def test_weighted_cost(self):
        b = TokenBucket(10, 1, clock=self.clock)
        self.assertTrue(b.allow(7))
        self.assertFalse(b.allow(4))
        self.assertTrue(b.allow(3))

    def test_remaining_reported(self):
        b = TokenBucket(5, 1, clock=self.clock)
        self.assertEqual(b.allow(2).remaining, 3)

    def test_invalid_arguments(self):
        with self.assertRaises(ValueError):
            TokenBucket(0, 1)
        with self.assertRaises(ValueError):
            TokenBucket(1, 0)
        with self.assertRaises(ValueError):
            TokenBucket(1, 1).allow(0)

    def test_thread_safety_never_exceeds_capacity(self):
        b = TokenBucket(100, 0.000001, clock=self.clock)  # frozen clock, no refill
        granted = []

        def worker():
            n = sum(1 for _ in range(100) if b.allow())
            granted.append(n)

        threads = [threading.Thread(target=worker) for _ in range(8)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        self.assertEqual(sum(granted), 100)


class SlidingWindowLogTests(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()

    def test_limit_within_window(self):
        w = SlidingWindowLog(3, 10, clock=self.clock)
        self.assertEqual([bool(w.allow()) for _ in range(4)], [True, True, True, False])

    def test_requests_expire_after_window(self):
        w = SlidingWindowLog(2, 10, clock=self.clock)
        w.allow()
        self.clock.advance(5)
        w.allow()
        self.assertFalse(w.allow())
        self.clock.advance(5)  # first request is exactly 10s old -> out
        self.assertTrue(w.allow())
        self.assertFalse(w.allow())

    def test_no_boundary_burst(self):
        # A fixed window would allow 2 + 2 requests around the boundary.
        w = SlidingWindowLog(2, 10, clock=self.clock)
        self.clock.advance(9)
        self.assertTrue(w.allow())
        self.assertTrue(w.allow())
        self.clock.advance(2)  # t=11: a fixed window [10,20) would reset
        self.assertFalse(w.allow())

    def test_retry_after_points_to_oldest_expiry(self):
        w = SlidingWindowLog(2, 10, clock=self.clock)
        w.allow()
        self.clock.advance(3)
        w.allow()
        d = w.allow()
        self.assertFalse(d.allowed)
        self.assertAlmostEqual(d.retry_after, 7)
        self.clock.advance(d.retry_after)
        self.assertTrue(w.allow())

    def test_weighted_cost(self):
        w = SlidingWindowLog(5, 10, clock=self.clock)
        self.assertTrue(w.allow(3))
        self.assertFalse(w.allow(3))
        self.assertTrue(w.allow(2))
        self.assertEqual(w.count, 5)

    def test_cost_above_limit(self):
        w = SlidingWindowLog(2, 10, clock=self.clock)
        d = w.allow(3)
        self.assertFalse(d.allowed)
        self.assertTrue(math.isinf(d.retry_after))

    def test_memory_bounded_by_limit(self):
        w = SlidingWindowLog(5, 1, clock=self.clock)
        for _ in range(1000):
            w.allow()
            self.clock.advance(0.01)
        self.assertLessEqual(w.count, 5)

    def test_invalid_arguments(self):
        with self.assertRaises(ValueError):
            SlidingWindowLog(0, 1)
        with self.assertRaises(ValueError):
            SlidingWindowLog(1, 0)
        with self.assertRaises(ValueError):
            SlidingWindowLog(1, 1).allow(1.5)


class KeyedLimiterTests(unittest.TestCase):
    def test_keys_are_independent(self):
        clock = FakeClock()
        k = KeyedLimiter(lambda: TokenBucket(1, 1, clock=clock))
        self.assertTrue(k.allow("alice"))
        self.assertFalse(k.allow("alice"))
        self.assertTrue(k.allow("bob"))
        self.assertEqual(len(k), 2)

    def test_prune_idle_keys(self):
        clock = FakeClock()
        k = KeyedLimiter(lambda: TokenBucket(2, 1, clock=clock))
        k.allow("a")
        k.allow("b", 2)
        clock.advance(10)
        removed = k.prune(lambda lim: lim.tokens >= lim.capacity)
        self.assertEqual(removed, 2)
        self.assertEqual(len(k), 0)


if __name__ == "__main__":
    unittest.main()
