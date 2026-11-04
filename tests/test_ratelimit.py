from pramaan.api.ratelimit import RateLimiter


def test_flood_of_fake_clients_does_not_grow_memory_without_bound():
    now = [0.0]
    limiter = RateLimiter(5, 60.0, clock=lambda: now[0])
    for i in range(RateLimiter.MAX_CLIENTS + 500):
        now[0] += 0.001
        limiter.allow(f"fake-{i}")
    assert len(limiter._hits) <= RateLimiter.MAX_CLIENTS
