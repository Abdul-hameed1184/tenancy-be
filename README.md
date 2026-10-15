# PLEET Backend

The backend for **PLEET**, a property and rental management platform. It's a modular Django monolith on PostgreSQL, with Redis (Sentinel high availability), Django Channels for realtime, and Celery for background work.

The frontend contract is `../tenancy-frontenf/API_ENDPOINTS.md`. To point the frontend at this API, set this in the frontend's `.env` (no frontend code changes are needed):

```
VITE_API_BASE_URL=http://localhost:8000/api/v1
```

---

## Architecture

```
                   Frontend (Vite :5173)
            REST /api/v1/...        WS /ws/threads/<id>/  /ws/notifications/
                    |                         |
            (nginx: TLS, body limits, WS upgrade)   -- optional
                    |                         |
   +----------------v-------------------------v------------------+
   | ASGI: gunicorn + uvicorn workers (N replicas, stateless)    |
   |   http      -> Django/DRF: auth -> permission -> serializer |
   |                -> service (transaction) -> domain event     |
   |   websocket -> Origin check -> ticket auth -> consumer      |
   |                -> same services as REST                     |
   +-----+-------------------------------+-----------------------+
         | rows + outbox (one txn)       | cache, throttles, WS tickets,
         v                               v channel layer, Celery broker
   +-------------+          +------------------------------------------+
   | PostgreSQL  |          | Redis Sentinel group                      |
   | source of   |          |  primary + 2 replicas + 3 sentinels (q=2) |
   | truth       |          |  never the source of truth                |
   +------^------+          +----------^-------------------^------------+
          |                            | broker            | group_send
   +------+----------------------------+--+      +----------+--------+
   | Celery workers                       |      | Celery Beat (1)   |
   | outbox dispatch, notifications,      |      | reminders, relay, |
   | emails, WS fan-out                   |      | cleanup           |
   +--------------------------------------+      +-------------------+
```

**Request flow:** view (thin) → serializer (validate input) → **service** (business rules inside `transaction.atomic()`) → `publish(DomainEvent)`, which writes an **outbox row in the same transaction** → after commit, Celery delivers the event to its handlers (notifications, WebSocket fan-out, emails).

| Concern                                            | Where                                                                                 |
| -------------------------------------------------- | ------------------------------------------------------------------------------------- |
| Business rules, transactions, locking              | `apps/<domain>/services.py`                                                           |
| Read queries, row scoping per role                 | `apps/<domain>/selectors.py`                                                          |
| API shape (camelCase contract ↔ snake_case models) | `apps/<domain>/serializers.py`                                                        |
| Domain events and outbox                           | `apps/common/events.py`, `apps/common/tasks.py`                                       |
| Realtime                                           | `apps/messaging/consumers.py`, `apps/notifications/consumers.py`, `apps/common/ws.py` |
| Redis topology                                     | `config/settings/redis_topology.py`                                                   |

Apps: `accounts`, `agents`, `properties`, `tenancies`, `payments`, `maintenance`, `inspections`, `messaging`, `notifications`, `reports`, `dashboards`, `audit`, `common`.

Property listings store photos and videos as secure URLs. Square footage is optional in the API and database; a missing value is returned as `null`. Property creation and update validation lives in `apps/properties/serializers.py`, while schema changes are applied through Django migrations.

---

## Local setup

Requirements: Python 3.14 and PostgreSQL 14+. Redis is optional locally: without it the app uses an in-process cache, an in-memory channel layer, and inline Celery tasks.

```bash
git clone <repo> && cd tenancy-backend
python -m venv venv
venv\Scripts\activate                 # Windows   (source venv/bin/activate on Unix)
pip install -r requirements/development.txt
cp .env.example .env                  # set SECRET_KEY and DATABASE_URL
```

Create the database. The role needs `CREATEDB` so the test runner can create `test_pleet`:

```sql
CREATE ROLE pleet LOGIN PASSWORD 'pleet_dev_password' CREATEDB;
CREATE DATABASE pleet OWNER pleet;
```

```bash
python manage.py migrate
python manage.py seed_data            # demo accounts, see below
python manage.py runserver            # ASGI via daphne: HTTP + WebSockets on :8000
```

To run Celery locally, set `REDIS_URL=redis://localhost:6379` in `.env`, then:

```bash
celery -A config worker -l info -P solo     # Windows has no prefork pool
celery -A config beat -l info
```

### Demo accounts (`seed_data`)

Every account uses the password `PleetDemo!2026`, overridable with `SEED_PASSWORD`. Ids are deterministic (uuid5), so reseeding is idempotent. The command refuses to run with `DEBUG=False` unless you pass `--force`.

| Role     | Email                                                                       |
| -------- | --------------------------------------------------------------------------- |
| admin    | admin@pleet.test                                                            |
| landlord | landlord@pleet.test, landlord2@pleet.test                                   |
| agent    | agent@pleet.test (verified), agent2@pleet.test (pending), agent3@pleet.test |
| tenant   | tenant@pleet.test, tenant2@pleet.test                                       |

---

## Docker

```bash
docker compose up --build -d                       # needs SECRET_KEY (50+ chars) in .env
docker compose exec web python manage.py seed_data --force
docker compose --profile proxy up -d nginx         # optional reverse proxy on :8080
```

| Service                              | Role                                                             |
| ------------------------------------ | ---------------------------------------------------------------- |
| `web`                                | gunicorn + uvicorn workers (ASGI: HTTP and WebSocket), port 8000 |
| `worker`                             | Celery worker: outbox dispatch, notifications, emails            |
| `beat`                               | Celery Beat. **Exactly one.**                                    |
| `migrate`                            | One-shot `migrate`. `web`, `worker` and `beat` wait for it.      |
| `postgres`                           | PostgreSQL 18                                                    |
| `redis-primary`, `redis-replica-1/2` | Redis 7 with AOF (`everysec`), `volatile-lru`                    |
| `sentinel-1/2/3`                     | Redis Sentinel, quorum 2, master name `pleet-core`               |
| `nginx`                              | Optional (`proxy` profile): body limits, WebSocket upgrade       |

### Redis failover drill

```bash
python scripts/redis_failover_drill.py     # kills the primary and checks the app recovers
docker compose start redis-primary         # the old primary rejoins as a replica
```

The drill tests the application, not just Redis. Before the failover it checks WebSocket chat and Celery-delivered notifications. It then stops `redis-primary`, checks that REST keeps serving, waits for promotion, and re-checks realtime and Celery on the new primary.

Measured locally:

| Step                                | Result               |
| ----------------------------------- | -------------------- |
| Sentinels promote a replica         | 5.9 s                |
| Realtime and Celery fully recovered | 7.2 s after the kill |
| REST during the failover window     | 200 throughout       |

**Why fixed IPs:** Redis nodes and sentinels use fixed IPs on their own network (`172.28.0.0/24`). When a container stops, Docker's DNS deletes its hostname. Sentinels monitoring _hostnames_ then stall on failed lookups, enter TILT mode and **never fail over**, which an earlier version of this setup did during the drill. Clients still reach the sentinels by name.

---

## Services and responsibilities

| Technology      | Responsibility                                                                                                                                                 |
| --------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Django**      | ORM, migrations, password hashing (Argon2), admin (ops console), ASGI app                                                                                      |
| **DRF**         | Serializers, views, permissions, throttling, consistent JSON errors                                                                                            |
| **PostgreSQL**  | Source of truth. Integrity rules live in the database: partial unique indexes, CHECKs, append-only triggers. Also row locks, `pg_trgm` search and aggregation. |
| **Redis**       | Cache, rate-limit counters, WebSocket tickets, channel layer, Celery broker. **Never the source of truth.**                                                    |
| **Channels**    | WebSocket consumers, plus groups fanned out through the Redis channel layer                                                                                    |
| **Celery**      | Outbox delivery, notifications, emails. Tasks retry with exponential backoff and are idempotent.                                                               |
| **Celery Beat** | Scheduled jobs (below), stored in the database (`django-celery-beat`)                                                                                          |

### Redis is not a single point of failure

1. **Redundancy.** Sentinel watches the primary. If it fails, a replica is promoted automatically. Every client (django-redis, channels-redis, Celery/kombu) asks the sentinels for the current primary, so it follows the failover.
2. **Graceful degradation.** Redis outages degrade the app; they don't break correctness:

| When Redis is unavailable | What happens                                                                                                    |
| ------------------------- | --------------------------------------------------------------------------------------------------------------- |
| Cache                     | Reads miss and are served from PostgreSQL (`IGNORE_EXCEPTIONS`).                                                |
| Auth rate limits          | Fall back to per-process counters. Limits get weaker but are never disabled.                                    |
| Celery broker             | The event stays pending in the outbox, and the Beat relay re-enqueues it within about 30s of Redis returning.   |
| WebSockets                | Connections can't be opened. REST keeps working, and every message is already in PostgreSQL.                    |
| `/health/ready/`          | Reports Redis as `degraded` but stays 200, so a Redis blip doesn't pull every web pod out of the load balancer. |

Key naming (Django prefixes cache keys with `pleet:1:`):

- `cache:<namespace>:<name>:v<N>:<hash>` (cached data), plus `cache:<namespace>:version`
- `pleet:throttle:<scope>:<ident>` (rate-limit counters)
- `ws:ticket:<sha256>` (WebSocket tickets)
- `pleet:channels*` (channel layer)

Logical databases: 0 is the Celery broker, 1 is cache/throttles/tickets, 2 is the channel layer.

---

## Authentication

- **`POST /auth/login`** and **`/auth/register`** return `{ user, token }`. `token` is a short-lived access JWT (60 min by default, `JWT_ACCESS_TOKEN_LIFETIME_MINUTES`), sent as `Authorization: Bearer <token>`. The `role` field on login is accepted and ignored: `user.role` in the response is the account's real role.
- The **refresh token** lives only in an HttpOnly cookie (`pleet_refresh`) scoped to `/api/v1/auth/`. JavaScript can never read it.
- **Sessions:**
  - Every login creates an `AuthSession`. Access tokens carry its id (`sid`), and authentication checks that the session is live in the same single query that loads the user.
  - So `POST /auth/logout`, or a password reset, **invalidates tokens immediately**.
  - `POST /auth/refresh` (requires the `X-Requested-With: XMLHttpRequest` header) **rotates** the refresh token. Every refresh token works once.
  - Presenting an already-rotated token is treated as theft and **revokes the whole session**.
  - Rotation locks the session row, so two concurrent refreshes can't both succeed.
- **Password reset:** `POST /auth/forgot-password` always returns 204, so it can't be used to discover accounts. The email links to `<frontend>/auth/reset-password?token=...`. The token is stateless (an HMAC), expires after 1 hour, and stops working once the password changes. Resetting revokes every session.
- **Rate limits:**

  | Endpoint              | Limit                  |
  | --------------------- | ---------------------- |
  | login                 | 5/min per IP and email |
  | register              | 10/hour per IP         |
  | forgot/reset password | 3/min per IP           |
  | refresh               | 30/min per IP          |

### Email verification

- Registration emails a link to `<frontend>/auth/verify-email?token=...`. The token is the user id plus the current email, signed and timestamped. It's valid for 3 days (`EMAIL_VERIFICATION_TIMEOUT`) and stops working if the email changes.
- Until the user verifies:
  - they can sign in, read `/auth/me` and use `POST /auth/resend-verification` (3/min, always 204);
  - every dashboard API answers `403 {"message": "...", "code": "email_not_verified"}`. The check runs in every role permission (`HasRole`/`IsAgent`…) and in `IsVerified`.
  - Public pages (properties, agents) keep working.
- `POST /auth/verify-email {token}` is idempotent. The welcome email is sent on first verification.
- Accounts that existed before this feature were marked verified by a data migration. Superusers and `seed_data` accounts start verified.

## Image uploads (Cloudinary, direct from the browser)

1. The browser calls `POST /api/v1/uploads/signature {"purpose": "property_photo" | "avatar"}`.
2. Django signs the upload parameters with `CLOUDINARY_API_SECRET`: a folder per user (`pleet/<purpose>/<userId>`), a random `public_id`, the allowed formats, and a `c_limit` resize. The secret never leaves the server.
3. The browser POSTs the file **directly to Cloudinary** with those fields, so the file never passes through Django.
4. The returned `secure_url` is saved as a property photo or `avatarUrl`. The API accepts Cloudinary URLs only from the uploader's own folder on our account.

Configure it with `CLOUDINARY_CLOUD_NAME`, `CLOUDINARY_API_KEY` and `CLOUDINARY_API_SECRET` (see `.env.example`). Without them the endpoint answers 503.

## Transactional email and deliverability

Account verification, password reset, welcome, and selected notification messages are sent as multipart email: a readable plain-text part plus a responsive HTML alternative. The templates are intentionally text-first, use inline styling, contain no tracking pixels or remote decorative assets, and include a copyable URL as well as a button.

Production startup requires SMTP host credentials and a valid `DEFAULT_FROM_EMAIL` on a real sender domain. Configure and verify SPF and DKIM records with the sending provider, and publish a DMARC policy for that domain. Use the same aligned domain in the visible From address and the provider's authenticated sending domain. Monitor provider bounce, complaint, and reputation reports; template changes alone cannot guarantee inbox placement.

## Authorization

Authorization has three layers, all server-side:

1. **Role:** `IsAdmin`, `IsLandlord`, `IsAgent`, `IsTenant`, `HasRole(...)`.
2. **Scope:** every private list and detail starts from `selectors.visible_to(user)`, so rows outside your scope are a **404**:
   - a landlord sees their own properties' data;
   - an agent sees properties they **actively** manage;
   - a tenant sees their own data.

   Query filters (`landlordId`, `agentId`…) apply _inside_ that scope and can only narrow it.

3. **Object:** ownership checks on writes (owning landlord, managing agent, thread participant).

Ids sent by the client (`landlordId`, `tenantId`, `senderId`, `loggedByAgentId`, `reportedById`, `?userId=`) are either ignored in favour of the token's user, or checked against it (a mismatch is a 403).

---

## WebSockets

1. `POST /api/v1/realtime/ticket` (with your Bearer token) returns `{ "ticket": "...", "expiresIn": 30 }`.
2. Connect within 30 s, using each ticket once:
   - `ws://localhost:8000/ws/threads/<threadId>/?ticket=...`, for chat in one thread
   - `ws://localhost:8000/ws/notifications/?ticket=...`, for your notification feed

Tickets exist because browsers can't attach an `Authorization` header to a WebSocket, and a JWT in the URL would leak into logs. A ticket is random, stored only as a hash, expires in 30 s, works once, and is tied to the session that created it.

**Chat messages:**

```jsonc
// client -> server
{"type": "message.send", "body": "Is the viewing still on?"}
// server -> every participant (including the sender)
{"type": "message.created", "message": {"id": "...", "threadId": "...", "senderId": "...", "body": "...", "sentAt": "..."}}
// server -> the offending socket only
{"type": "error", "message": "..."}
```

**Close codes:**

- `4401`: not authenticated (missing, invalid, expired or reused ticket).
- `4403`: not a participant, or removed mid-session.
- Connections from origins outside `CORS_ALLOWED_ORIGINS` are refused. CORS doesn't cover WebSockets, so this check is explicit.

Messages sent over REST are pushed to open sockets too. Both paths use the same service and the same participant check.

---

## Background jobs

**Celery tasks:**

- `dispatch_event`: delivers outbox events, with exponential backoff and jitter.
- `send_notification_email`: sends at most once, tracked by `emailed_at`.
- `send_password_reset_email`: the token is generated inside the worker, so no credential is ever in the broker.
- `send_welcome_email`.

**Celery Beat** (Africa/Lagos time):

| Schedule     | Task                      | What it does                                         |
| ------------ | ------------------------- | ---------------------------------------------------- |
| every 30 s   | `relay_pending_events`    | Re-enqueues outbox rows still undelivered after 30 s |
| 07:00 daily  | `send_rent_due_reminders` | Tenancies due within 7 days → tenant and agent       |
| 00:15 daily  | `flag_overdue_rent`       | Overdue tenancies → tenant, agent and landlord       |
| 03:00 daily  | `cleanup_auth_sessions`   | Deletes expired or long-revoked sessions             |
| Sunday 04:00 | `purge_dispatched_events` | Deletes delivered outbox rows older than 30 days     |

Every job is **idempotent**. Notifications have a unique `dedupe_key`, so re-running a job, running it late, or delivering an event twice never duplicates anything.

---

## Data integrity and concurrency highlights

**Rules PostgreSQL enforces:**

- **One active agent per property:** a partial unique index on `property WHERE active`. Assigning locks the property row (`SELECT … FOR UPDATE`), so concurrent assignments run one after the other.
- **The payment ledger is append-only:** no update or delete through the API, the model refuses, and a **PostgreSQL trigger** rejects `UPDATE`/`DELETE` even from raw SQL.
  - Logging a payment locks the tenancy row.
  - `UNIQUE (tenancy, due_date) WHERE status='paid'` turns a duplicate concurrent payment into a 409.
  - A paid entry moves `nextDueDate` to the later of its current value and `dueDate + 1 year`, so it never moves backwards.
- **The audit log is append-only** (also a trigger). The single allowed change is the FK's `SET NULL` when a user is deleted.
- **One current tenancy per tenant, one current tenant per unit, and every status set** are enforced with partial unique indexes and CHECK constraints.

**Race handling:**

- **Status changes** (maintenance, inspections, reports) are a single conditional `UPDATE … WHERE status IN (allowed)`. Exactly one of two racing requests wins; the other gets a 409.
- **Concurrency tests** use real threads against PostgreSQL for: refresh rotation, agent assignment, duplicate payments, maintenance and inspection transitions, and verification decisions.

## API documentation

- Swagger UI: **http://localhost:8000/api/docs/**
- OpenAPI schema: **http://localhost:8000/api/schema/**

CI validates the schema with warnings treated as errors.

The frontend is a separate React/TypeScript application in `../tenancy-frontenf`. Its overview and local setup are documented in `../tenancy-frontenf/README.md`; production deployment steps are in `../DEPLOYMENT.md`.

**Conventions:**

- Responses are raw JSON (no envelope).
- Errors are always `{"message": "..."}`. Validation errors add `errors: {field: [...]}`.
- A 401 means only "log in again". Permission problems are 403, and resources outside your scope are 404.
- Ids are UUIDv7 strings and timestamps are UTC ISO-8601.
- Calendar dates (`leaseStart`, `dueDate`) are sent as `YYYY-MM-DDT00:00:00.000Z`.
- Trailing slashes are optional.
- **Pagination:** none. The contract expects full arrays; the notification feed is capped at 100 items.

**Additive endpoints** (not in the contract):

- `POST /auth/refresh`
- `POST /auth/verify-email`
- `POST /auth/resend-verification`
- `POST /uploads/signature`
- `POST /realtime/ticket`
- `GET /notifications`
- `POST /notifications/<id>/read`
- `POST /notifications/read-all`

## Health

| Path             | Checks                                                                               |
| ---------------- | ------------------------------------------------------------------------------------ |
| `/health/`       | Liveness: touches no dependency                                                      |
| `/health/ready/` | Readiness: requires PostgreSQL; reports Redis (`ok`, `degraded` or `not_configured`) |

## Testing

```bash
pytest                                  # full suite (deprecation warnings are errors)
pytest --cov                            # coverage; CI fails under 90%
PLEET_TEST_REDIS_URL=redis://localhost:6379 pytest tests/test_redis_integration.py
ruff check . && ruff format --check .
python manage.py makemigrations --check --dry-run
```

**What's covered:**

- auth, sessions and rotation;
- the role × endpoint permission matrix and scoping;
- every contract endpoint;
- database constraints and triggers;
- concurrency, using real threads;
- WebSockets, through the full ASGI stack;
- Celery retries and idempotency;
- Beat jobs;
- one test per dashboard statistic;
- **query budgets** pinned on every list endpoint, to catch N+1 queries.

## Environment variables

See `.env.example`. The main ones:

| Variable                                                                                  | Purpose                                                                   |
| ----------------------------------------------------------------------------------------- | ------------------------------------------------------------------------- |
| `SECRET_KEY`                                                                              | Required in production (50+ chars)                                        |
| `DEBUG`, `ALLOWED_HOSTS`                                                                  | Standard Django settings                                                  |
| `DATABASE_URL`                                                                            | PostgreSQL DSN                                                            |
| `REDIS_SENTINELS`, `REDIS_MASTER_NAME`                                                    | High-availability Redis (`host:26379,...`)                                |
| `REDIS_URL`                                                                               | Single-node Redis, for simple development                                 |
| `REDIS_PASSWORD`                                                                          | Redis auth                                                                |
| `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND`                                              | Override the broker derived from the Redis settings                       |
| `FRONTEND_URL`, `CORS_ALLOWED_ORIGINS`                                                    | Reset-email links; allowed browser origins for REST and WebSocket         |
| `JWT_ACCESS_TOKEN_LIFETIME_MINUTES`, `JWT_REFRESH_TOKEN_LIFETIME_DAYS`, `JWT_SIGNING_KEY` | Token lifetimes and an optional separate signing key                      |
| `EMAIL_*`, `DEFAULT_FROM_EMAIL`                                                           | SMTP in production                                                        |
| `LOG_LEVEL`, `LOG_FORMAT`                                                                 | `json` in production: one object per line, with request id and redaction  |
| `NUM_PROXIES`                                                                             | Trusted proxies in front, for correct client IPs in rate limits and audit |
| `PORTFOLIO_VALUE_MULTIPLIER`                                                              | Landlord asset-value estimate (default 6)                                 |
| `SEED_PASSWORD`                                                                           | Password for `seed_data` accounts                                         |

See [docs/REVIEW.md](docs/REVIEW.md) for the final security and architecture review, the known limitations, and how the design extends (Kafka, OpenSearch, object storage, separate realtime infrastructure).
#   t e n a n c y - b e  
 