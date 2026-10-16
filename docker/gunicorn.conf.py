"""gunicorn supervising uvicorn (ASGI) workers: process management + async HTTP/WebSocket."""

import os

bind = "0.0.0.0:8000"
worker_class = "uvicorn_worker.UvicornWorker"
workers = int(os.environ.get("WEB_CONCURRENCY", "2"))
# Long-lived WebSockets are fine: the timeout only kills workers that stop heartbeating.
timeout = 60
graceful_timeout = 30  # finish in-flight requests on deploys / SIGTERM
keepalive = 5
max_requests = 2000  # recycle workers periodically to bound memory growth
max_requests_jitter = 200
accesslog = None  # the app writes its own structured access log (RequestIdMiddleware)
errorlog = "-"
# Trust X-Forwarded-* only from the reverse proxy network in front of us.
forwarded_allow_ips = os.environ.get("FORWARDED_ALLOW_IPS", "127.0.0.1")
