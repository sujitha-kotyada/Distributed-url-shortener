# Load Testing & Performance Benchmarking

This directory contains the [Locust](https://locust.io/) performance test suite for the **Distributed URL Shortener & Analytics Platform**.

The suite simulates concurrent user workloads across:
- **Cached Redirects (`cache_warm`)**: Evaluates Redis memory lookup throughput and HTTP 307 redirect latency.
- **Cold Cache Lookups (`cache_cold`)**: Evaluates PostgreSQL lookup latency and subsequent cache population.
- **URL Creation (`creation`)**: Evaluates PostgreSQL sequence ID generation and Base62 encoding under concurrent writes.
- **Analytics Queries (`analytics`)**: Evaluates database aggregation queries for click statistics.
- **Rate Limiting**: Verifies that requests exceeding configured thresholds safely receive HTTP 429 without degrading API stability.

---

## Prerequisites

Install Locust in your local Python environment:

```bash
pip install locust
```

Ensure the services are running either directly or via Docker Compose:
```bash
docker compose up -d
```

---

## Running the Load Tests

### 1. Headless Execution (Automated / CI Benchmarking)

To run an automated test simulating 50 concurrent users spawning at 10 users/sec for 1 minute:

```bash
locust -f locustfile.py --headless -u 50 -r 10 --run-time 1m --host http://localhost:8001
```

> **Target Host:**
> - `http://localhost:8001`: Benchmarks through the Nginx reverse proxy load-balancing between `api-1` and `api-2`.

### 2. Interactive Web UI

To run with Locust's real-time browser dashboard:

```bash
locust -f locustfile.py --host http://localhost:8001
```

Open your browser to:
[http://localhost:8089](http://localhost:8089)

Configure:
- **Number of users**: `100`
- **Ramp up (users started/second)**: `10`
- **Host**: `http://localhost:8001`

### 3. Targeted Tagged Runs

You can filter tasks by tags to benchmark specific subsystems:

- **Benchmark only cached redirects:**
  ```bash
  locust -f locustfile.py --headless -u 100 -r 20 --run-time 30s --tags redirect cache_warm --host http://localhost:8001
  ```

- **Benchmark URL creation:**
  ```bash
  locust -f locustfile.py --headless -u 20 -r 5 --run-time 30s --tags creation --host http://localhost:8001
  ```

---

## Correlating with Observability

While the load test runs:

1. **Prometheus Metrics**:
   Visit [http://localhost:9090](http://localhost:9090) to view:
   - `rate(url_shortener_http_requests_total[1m])`
   - `url_shortener_cache_hits_total` vs `url_shortener_cache_misses_total`
   - `url_shortener_worker_processed_total`

2. **Grafana Dashboard**:
   Visit [http://localhost:3001](http://localhost:3001) (`admin` / `admin`) to view real-time request rates, latency percentiles (p50, p95, p99), and cache hit ratios.

3. **Rate Limiting Observation**:
   Under high concurrency from a single IP, Locust will record HTTP 429 responses. This confirms that the Redis sliding-window rate limiter is protecting the backend from abusive traffic.
