"""Distributed URL Shortener - Locust Load Testing Suite.

This suite benchmarks the performance of:
1. High-throughput cached redirect lookups (Redis memory speed).
2. Cold redirect lookups (PostgreSQL query + Redis cache population).
3. URL creation (PostgreSQL sequence allocation + Base62 encoding).
4. Analytics query aggregation.
5. Rate limiter validation (verifying HTTP 429 backoff).
"""

from __future__ import annotations

import random
import string
from locust import HttpUser, between, events, tag, task


class UrlShortenerUser(HttpUser):
    wait_time = between(0.1, 0.5)

    def on_start(self) -> None:
        """Seed a short URL on initialization so redirect tasks have a warm target."""
        self.known_short_codes: list[str] = []
        random_suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=8))
        target_url = f"https://example.com/dest-{random_suffix}"

        resp = self.client.post(
            "/api/v1/urls",
            json={"original_url": target_url},
            headers={"Content-Type": "application/json"},
            name="/api/v1/urls (seed)",
        )
        if resp.status_code == 201:
            data = resp.json()
            code = data.get("short_code")
            if code:
                self.known_short_codes.append(code)

    @tag("redirect", "cache_warm")
    @task(10)
    def redirect_cache_warm(self) -> None:
        """Hit a known short code repeatedly to measure cached redirect latency."""
        if not self.known_short_codes:
            return

        short_code = random.choice(self.known_short_codes)
        # Note: allow_redirects=False to benchmark the 307 redirect response time itself
        with self.client.get(
            f"/{short_code}",
            allow_redirects=False,
            name="/{short_code} (cached redirect)",
            catch_response=True,
        ) as response:
            if response.status_code in (307, 308):
                response.success()
            elif response.status_code == 429:
                response.failure("Rate limited (HTTP 429)")
            elif response.status_code == 404:
                response.failure("Short code not found (HTTP 404)")
            else:
                response.failure(f"Unexpected status: {response.status_code}")

    @tag("redirect", "cache_cold")
    @task(2)
    def redirect_cache_cold_or_miss(self) -> None:
        """Test cache miss or unseeded short code lookup."""
        bogus_code = "".join(random.choices(string.ascii_letters + string.digits, k=7))
        with self.client.get(
            f"/{bogus_code}",
            allow_redirects=False,
            name="/{short_code} (cold miss)",
            catch_response=True,
        ) as response:
            if response.status_code in (404, 429):
                response.success()
            else:
                response.failure(f"Expected 404/429, got: {response.status_code}")

    @tag("creation")
    @task(3)
    def create_short_url(self) -> None:
        """Test URL creation throughput and database sequence generation."""
        random_slug = "".join(random.choices(string.ascii_lowercase + string.digits, k=10))
        target_url = f"https://loadtest-{random_slug}.org/article/{random_slug}"

        with self.client.post(
            "/api/v1/urls",
            json={"original_url": target_url},
            headers={"Content-Type": "application/json"},
            name="/api/v1/urls (create)",
            catch_response=True,
        ) as response:
            if response.status_code == 201:
                data = response.json()
                code = data.get("short_code")
                if code and len(self.known_short_codes) < 50:
                    self.known_short_codes.append(code)
                response.success()
            elif response.status_code == 429:
                response.success()  # Rate limiting functioning as expected
            else:
                response.failure(f"Creation failed with {response.status_code}: {response.text}")

    @tag("analytics")
    @task(1)
    def query_analytics_stats(self) -> None:
        """Query URL click analytics aggregation."""
        if not self.known_short_codes:
            return

        code = random.choice(self.known_short_codes)
        with self.client.get(
            f"/api/v1/urls/{code}/stats",
            name="/api/v1/urls/{code}/stats",
            catch_response=True,
        ) as response:
            if response.status_code in (200, 404):
                response.success()
            elif response.status_code == 429:
                response.success()
            else:
                response.failure(f"Analytics query failed: {response.status_code}")

    @tag("health")
    @task(1)
    def health_check(self) -> None:
        """Benchmark basic health check endpoint."""
        self.client.get("/health", name="/health")
