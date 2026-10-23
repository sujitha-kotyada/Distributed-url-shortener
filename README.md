# Distributed URL Shortener & Analytics Platform

[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688.svg?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-336791.svg?logo=postgresql&logoColor=white)](https://www.postgresql.org)
[![Redis](https://img.shields.io/badge/Redis-7.0+-DC382D.svg?logo=redis&logoColor=white)](https://redis.io)
[![React](https://img.shields.io/badge/React-19-61DAFB.svg?logo=react&logoColor=black)](https://react.dev)
[![TypeScript](https://img.shields.io/badge/TypeScript-5.0+-3178C6.svg?logo=typescript&logoColor=white)](https://www.typescriptlang.org)
[![Docker](https://img.shields.io/badge/Docker-Compose-2496ED.svg?logo=docker&logoColor=white)](https://www.docker.com)
[![Prometheus](https://img.shields.io/badge/Prometheus-Monitoring-E6522C.svg?logo=prometheus&logoColor=white)](https://prometheus.io)
[![Grafana](https://img.shields.io/badge/Grafana-Dashboards-F46800.svg?logo=grafana&logoColor=white)](https://grafana.com)

A production-grade, distributed URL shortening service and real-time click analytics platform engineered with **FastAPI**, **PostgreSQL**, **Redis Streams**, **Docker Compose**, and **React 19 + TypeScript**.

Designed to demonstrate core distributed systems patterns: **collision-free distributed ID allocation**, **sub-millisecond cache-aside reads**, **asynchronous stream ingestion with consumer groups and DLQ**, **atomic sliding-window rate limiting**, and **full-stack observability**.

---

## Key Architectural Highlights

- **Collision-Free ID Allocation**: Uses PostgreSQL 64-bit sequence generation mapped bijectively via **Base62** encoding (`[0-9A-Za-z]`), avoiding hash collisions and distributed locking.
- **Sub-Millisecond Redirects**: Redis cache-aside layer provides ultra-low latency HTTP 307 redirects with fail-safe fallback to PostgreSQL upon cache disconnects.
- **Asynchronous Analytics Ingestion**: Redirect latency is decoupled from database writes. Events are published via `XADD` to bounded **Redis Streams**, consumed by an autonomous worker in a consumer group, and persisted into PostgreSQL with idempotency.
- **Dead-Letter Queue (DLQ)**: Poison pills or messages failing repeatedly (> 3 attempts) are diverted to a dedicated DLQ stream (`url_shortener:redirect_events:dlq`) with full diagnostic error payloads.
- **Atomic Sliding-Window Rate Limiter**: High-precision rate limiting implemented via custom Redis Lua scripts, enforcing tiered limits (20 req/min creation, 100 req/min redirect lookups) returning standard HTTP 429 responses.
- **JWT Authentication & Link Ownership**: Secure user registration and login with bcrypt password hashing, allowing authenticated users to manage and inspect personal link portfolios while preserving anonymous creation.
- **Load Balancing**: Nginx reverse proxy distributing incoming requests round-robin across multiple FastAPI replicas.
- **Full Observability Stack**: Native Prometheus metrics endpoint (`/metrics`) integrated with pre-provisioned Prometheus scraping and Grafana dashboard visualization.
- **Modern Glassmorphic Frontend**: Dark-themed, responsive dashboard built with React 19, TypeScript, and Vite.

---

## System Architecture

```
                    +------------------------+
                    | Client / Web Browser   |
                    +-----------+------------+
                                |
                    +-----------v------------+
                    |   Nginx Load Balancer  | (Port 8001)
                    +-----+------------+-----+
                          |            |
             +------------v---+    +---v------------+
             | FastAPI (api-1)|    | FastAPI (api-2)| (Internal :8000)
             +-------+--------+    +---+------------+
                     |                 |
       +-------------+-----------------+-------------+
       |                                             |
+------v-------------------+            +------------v------------+
|  Redis 7                 |            |  PostgreSQL 16          |
|  - Cache (GET /{code})   |            |  - Sequence Allocation  |
|  - Rate Limit (Lua)      |            |  - URLs & Users Store   |
|  - Streams (XADD events) |            |  - Analytics Tables     |
+------+-------------------+            +------------^------------+
       |                                             |
       | XREADGROUP                                  | Idempotent Insert
+------v-------------------+                         |
| Standalone Analytics     +-------------------------+
| Worker Process           | (Dead Letter Queue on Poison Pill)
+--------------------------+
```

For complete technical specifications, see [docs/architecture.md](docs/architecture.md).

---

## Repository Structure

```
Distributed-url-shortener/
├── docker-compose.yml              # Complete orchestration (PG, Redis, APIs, Worker, Nginx, Prom, Grafana, FE)
├── .env.example                    # Environment variable template
├── backend/
│   ├── Dockerfile                  # Production container definition
│   ├── alembic/                    # Database migrations (202610110004 & 202610110005)
│   ├── pyproject.toml              # Dependencies & build configuration
│   ├── src/url_shortener/
│   │   ├── main.py                 # FastAPI application factory & routes
│   │   ├── api/                    # Routers: health, redirects, auth, urls
│   │   ├── core/                   # Security, rate limiter (Lua), cache, metrics
│   │   ├── models/                 # SQLAlchemy models (User, Url, RedirectEvent)
│   │   ├── schemas/                # Pydantic validation schemas
│   │   └── services/               # ID allocation, worker, stream publishing
│   └── tests/                      # 113 comprehensive unit & integration tests
├── frontend/
│   ├── Dockerfile                  # Nginx-based production frontend container
│   ├── src/                        # React 19 + TypeScript source
│   │   ├── App.tsx                 # Glassmorphic dashboard & analytics inspector
│   │   ├── api.ts                  # Typed client for backend REST API
│   │   └── index.css               # Design system & responsive styles
│   └── package.json
├── docker/
│   ├── nginx/nginx.conf            # Nginx upstream load balancer configuration
│   ├── prometheus/prometheus.yml   # Prometheus scraper configuration
│   └── grafana/                    # Provisioned datasources and dashboard JSON
└── load_tests/
    ├── locustfile.py               # Locust load & resilience test suite
    └── README.md                   # Load testing instructions & benchmarks
```

---

## Quickstart with Docker Compose

Ensure Docker and Docker Compose are installed.

1. **Clone the repository and prepare environment variables:**
   ```bash
   cp .env.example .env
   ```

2. **Launch the entire distributed system:**
   ```bash
   docker compose up --build -d
   ```

3. **Verify running containers:**
   ```bash
   docker compose ps
   ```

### Accessing Services

| Service | Port / URL | Credentials / Notes |
|---|---|---|
| **Frontend Web Dashboard** | [http://localhost:3000](http://localhost:3000) | Full UI for URL creation, auth, and analytics |
| **Nginx API Gateway** | [http://localhost:8001](http://localhost:8001) | Round-robin load balanced across API replicas |
| **Internal API Replicas** | `api-1:8000`, `api-2:8000` | FastAPI backend instances (internal network) |
| **Interactive API Docs** | [http://localhost:8001/docs](http://localhost:8001/docs) | Swagger UI |
| **Prometheus Metrics** | [http://localhost:9090](http://localhost:9090) | Metric scrapes & PromQL queries |
| **Grafana Dashboard** | [http://localhost:3001](http://localhost:3001) | User: `admin` / Password: configured via `GRAFANA_ADMIN_PASSWORD` in root `.env` |

### Security and Production Configuration

Before deploying or running in production, review and configure the following security settings in your root `.env` file:

- **JWT Secret Key (`JWT_SECRET_KEY`)**: When `ENVIRONMENT=production`, application startup validation strictly rejects the development default key and requires a unique, cryptographically strong secret of at least 32 characters.
- **Redis Exposure**: Redis is published on loopback (`127.0.0.1`) by default in Compose; do not expose Redis to public networks without authentication (`requirepass`) and TLS encryption.
- **CORS Allowed Origins (`CORS_ORIGINS`)**: Set to the explicit production frontend origin(s) (e.g., `["https://shortener.example.com"]`). Avoid wildcard origins when credentials are supported.
- **Trusted Proxies (`TRUSTED_PROXIES`)**: Configure only with the actual IP addresses or CIDR ranges of your trusted reverse proxies or load balancers. Do not blindly copy broad example subnet ranges. When left empty, incoming forwarding headers (`X-Forwarded-For`, `X-Real-IP`) are strictly ignored to prevent client IP spoofing.
- **Rate Limiting Fail-Open Behavior**: To prioritize core redirect and creation availability, rate limit checks fail open (allowing requests) if Redis is unreachable or degraded. During a Redis outage, rate limiting is not enforced, temporarily trading abuse protection for uptime.
- **Grafana Credentials (`GRAFANA_ADMIN_PASSWORD`)**: Replace the development placeholder password in `.env` before starting containers. In production, configure HTTPS, SSO/OAuth, and persistent storage.

---

## API Reference

### 1. URL Operations
- `POST /api/v1/urls`: Shorten a URL. Accepts optional custom alias or expiration time. Supports anonymous or authenticated requests.
- `GET /{short_code}`: Resolves the short code and performs an **HTTP 307** temporary redirect while publishing an asynchronous click event.
- `GET /api/v1/urls/my`: List all URLs owned by the authenticated user.
- `GET /api/v1/urls/{short_code}/stats`: Retrieve aggregated analytics (total clicks, hourly/daily click counts, unique referrers).

### 2. Authentication
- `POST /api/v1/auth/register`: Create a new user account.
- `POST /api/v1/auth/login`: Authenticate and receive a JWT bearer token.
- `GET /api/v1/auth/me`: Retrieve current user profile.

### 3. Health & Observability
- `GET /health`: Basic service liveness check.
- `GET /health/db`: Database connectivity verification.
- `GET /metrics`: Prometheus formatted metrics exposition.

---

## Local Development (Without Docker)

### Backend Setup

```bash
cd backend

# Install dependencies (Python 3.11+)
pip install -e .

# Run database migrations
alembic upgrade head

# Start FastAPI API server
uvicorn url_shortener.main:app --host 0.0.0.0 --port 8000 --reload

# Start the asynchronous analytics worker in a separate terminal
python -m url_shortener.services.analytics_worker
```

### Frontend Setup

```bash
cd frontend

# Install dependencies
npm install

# Start Vite development server
npm run dev
```

Dashboard will be accessible at [http://localhost:5173](http://localhost:5173).

---

## Testing & Quality Assurance

### Run Backend Unit & Integration Tests
The backend features a 113-test suite covering sequence ID allocation, Base62 roundtrips, Redis caching, stream consumer groups, DLQ handling, rate limiting, and analytics:

```bash
cd backend
python -m pytest -v
```

### Frontend Typecheck & Build
```bash
cd frontend
npm run build
```

### Run Performance & Load Tests
Simulate high-concurrency traffic using the Locust suite:

```bash
cd load_tests
pip install locust
locust -f locustfile.py --headless -u 50 -r 10 --run-time 1m --host http://localhost:8001
```

---

## License

This project is licensed under the MIT License.
