"""Tiny demo: ``python3 -m rate_limiter`` replays a burst against both algorithms."""

from .clock import FakeClock
from .limiters import SlidingWindowLog, TokenBucket


def main() -> None:
    clock = FakeClock()
    bucket = TokenBucket(capacity=5, refill_rate=1, clock=clock)
    window = SlidingWindowLog(limit=5, window=5, clock=clock)
    print("t(s)  token-bucket  sliding-window")
    for step in range(14):
        # 3 requests per simulated second
        results = [(bucket.allow().allowed, window.allow().allowed) for _ in range(3)]
        tb = "".join("Y" if r[0] else "." for r in results)
        sw = "".join("Y" if r[1] else "." for r in results)
        print(f"{step:>4}  {tb:<12}  {sw}")
        clock.advance(1)


if __name__ == "__main__":
    main()
