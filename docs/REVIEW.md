# PLEET Backend: Final Security and Architecture Review

**Date:** 2026-10-01.

**Scope:** every app in `apps/`, plus settings, ASGI, Celery and Docker.

**Status legend:**
- ✅ handled in code and tested
- ⚠️ mitigated, with a known residual risk
- ⏳ recommended next step, not built

## 1. Security

### Authentication and sessions

| # | Topic | Status | Notes |
|---|---|---|---|
| S1 | Password storage | ✅ | Argon2id, with PBKDF2 kept only to verify older hashes. Django's password validators run on register and reset. |
| S2 | Token revocation | ✅ | Access JWTs are bound to a server-side `AuthSession`. Logout and password reset take effect on the next request, not at token expiry. |
| S3 | Refresh token theft | ✅ | The refresh token is in an HttpOnly cookie, rotated on every use, with reuse detection that revokes the whole session. The rotation lock is tested with real threads. |
| S4 | Access token in `localStorage` (the frontend's choice) | ⚠️ | Any XSS on the frontend can read the token. Mitigated by the 60-minute lifetime and instant revocation. ⏳ The frontend should adopt the refresh-cookie flow, then cut the access lifetime to 5–15 minutes, and add a strict CSP on the frontend. |
| S5 | Account enumeration | ⚠️ | Login failures share one message. Forgot-password always returns 204, and its email is sent from Celery, so known and unknown emails take equal time. **Registration** necessarily reveals "email already exists"; it's limited to 10/hour per IP. |
| S6 | Brute force | ✅ | Login is limited per IP and email. If Redis is down, limits fall back to per-process counters, so they weaken rather than disappear. ⏳ Per-account lockout with backoff, and 2FA for admins. |
| S7 | Password reset tokens | ✅ | A stateless HMAC: expires after 1 hour, single use (it dies with the old password hash), generated inside the worker so it's never in the broker. |
| S8 | WebSocket authentication | ✅ | 30-second single-use tickets, stored only as hashes and tied to the session that created them; the JWT never goes in a URL. An explicit Origin check prevents cross-site WebSocket hijacking. |

### Authorization

| # | Topic | Status | Notes |
|---|---|---|---|
| A1 | Forged ids | ✅ | Every client-supplied id (`landlordId`, `tenantId`, `senderId`, `loggedByAgentId`, `reportedById`, `?userId=`) is ignored or checked against the token's user. |
| A2 | Seeing other users' data | ✅ | Private resources are scoped per role (`visible_to`), and out-of-scope rows are 404s. Covered by a role × endpoint matrix and tests that forged filters can't widen results. |
| A3 | Stale rights | ✅ | A replaced agent loses access immediately. Payment logging re-checks "is this agent still managing?" under the row lock. A removed thread participant is cut off mid-socket. |
| A4 | Public catalogue | ⚠️ | Per the contract, properties and agent cards are public, including `landlordId` and agent email and phone. Identity documents (`passportDocUrl`, `thirdPartyCheckRef`) are only shown to admins and the agent themself. |

### Platform

| # | Topic | Status | Notes |
|---|---|---|---|
| P1 | SQL injection | ✅ | ORM-only. The raw SQL lives in migrations (static trigger definitions) and tests. |
| P2 | Secrets in logs | ✅ | A handler-level redaction filter drops sensitive keys and masks `Bearer …` values. The access log leaves out query strings. Audit metadata is scrubbed too. |
| P3 | Production hardening | ✅ | `check --deploy` passes, and CI runs it. Settings: HSTS, secure cookies, `SECURE_PROXY_SSL_HEADER`, `X_FRAME_OPTIONS=DENY`, COOP, nosniff. Production refuses to start without a strong `SECRET_KEY` and `ALLOWED_HOSTS`. |
| P4 | Request size and DoS | ✅ | Django body limits plus nginx's `client_max_body_size`. Text fields have a maximum length. List endpoints have pinned query budgets. |
| P5 | Uploads | ⚠️ | There are no upload endpoints; photos are https URLs, validated. `STORAGES` is ready for S3 or Cloudinary via django-storages. ⏳ When uploads arrive: signed direct-to-bucket uploads with MIME, size and extension validation, and malware scanning. |
| P6 | Redis security | ⏳ | Supported via `REDIS_PASSWORD` but not enabled in the local compose. Production needs `requirepass`/ACLs plus TLS, and a private network. |
| P7 | Django admin | ⏳ | It's the operations console (tenancies and threads are created there). Restrict it by network or VPN, and require 2FA. |
| P8 | Dependency updates | ⏳ | Add Dependabot or Renovate, plus `pip-audit` in CI. |

## 2. Architecture

**What holds up well:**
- **The database is the source of truth.** Business rules are encoded as constraints and triggers in PostgreSQL, so a bug in Python, a script or the admin can't break them.
- **Services own transactions; views stay thin.** Locks are chosen per case: `select_for_update` where a decision needs other rows (assignment, payments, refresh rotation, verification), and a conditional `UPDATE … WHERE status IN (…)` for state machines.
- **The transactional outbox decouples side effects.**
  - Notifications, WebSocket fan-out and emails are event handlers.
  - Services never import the notifications app.
  - The broker can be swapped (Kafka/RabbitMQ) by changing `_enqueue()` and the relay only.
- **Redis is never on the correctness path.** Every Redis role has a defined degraded mode, backed by Sentinel failover.

**Verified failover:** `scripts/redis_failover_drill.py` kills the Redis primary under the running app.

| Measurement | Result |
|---|---|
| Promotion | 5.9 s |
| Realtime and Celery recovered | 7.2 s |
| REST during the window | uninterrupted |
| Old primary on restart | rejoins as a replica |

The drill also caught a real defect: hostname-based Sentinel monitoring sends sentinels into TILT mode under Docker DNS, and they never fail over. Fixed by switching to fixed IPs.

**Residual single points of failure:**
- **PostgreSQL:** use managed high availability or streaming replication with automated failover.
- **Celery Beat:** run one instance under a supervisor. Its jobs are idempotent and catch up after downtime. ⏳ `celery-redbeat` (with a lock) would give an active/passive Beat.

**Known simplifications:**
- One Redis Sentinel group serves every role, using `volatile-lru` so only cache keys can be evicted. At larger scale, split it into a cache group (`allkeys-lru`, no persistence) and a broker/channels group (`noeviction`, AOF).
- Stats are cached for 30 s by TTL only.
- The notification feed is capped at 100 items.

## 3. Contract gaps (need frontend/product decisions)

| Gap | Current handling |
|---|---|
| No endpoint to create tenancies or message threads | Created in the Django admin or `seed_data`. |
| No endpoint for an agent to submit verification (→ `pending`) | Seeded or set in the admin. |
| Frontend never refreshes tokens | `/auth/refresh` exists (additive). Until the frontend uses it, users re-login after 60 minutes. |
| No WebSocket client or notifications UI in the frontend | The backend is ready; the protocol is documented in the README and OpenAPI descriptions. |
| `portfolioValueChangePct`, `collectionRatePct` were hardcoded in the mock | Defined formulas, documented in `apps/dashboards/selectors.py`. |

**Decisions made along the way:**
- **Login `role`:** ignored, by your choice. The response's `user.role` is authoritative.
- **`nextDueDate`:** never moves backwards when an old period is paid late.
- **Property reads:** public, per the contract. Ownership applies to writes and to private data.
- **Payment status:** recorded as logged. The ledger is append-only, so "overdue" is surfaced through notifications rather than by editing rows.

## 4. Future evolution (no rewrite required)

- **Kafka / RabbitMQ:** publish outbox rows to the broker from the relay. Debezium CDC on `common_outboxevent` is the zero-code alternative. Handlers become consumers.
- **Search:** replace `pg_trgm` with OpenSearch, kept in sync by subscribing to property events.
- **Object storage:** switch `STORAGES["default"]` to S3 or Cloudinary.
- **Payment gateway:** a webhook endpoint verifies the provider's signature, then calls `payments.services.log_payment` (idempotency key = the provider's reference). `PaymentPaid` handlers already notify.
- **Separate realtime tier:** consumers depend only on services and the channel layer, so the ASGI WebSocket workers can be scaled or deployed separately from HTTP. A dedicated gateway (Centrifugo, Pusher) could subscribe to `MessageSent`.
- **Microservice candidates, if ever needed:**
  1. Notifications: already event-driven, and owns its own table.
  2. Realtime delivery.

  The rest of the domain shares transactions (assignment ↔ tenancy ↔ payments) and should stay together.
