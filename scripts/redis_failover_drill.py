"""
End-to-end Redis failover drill against the dockerised PLEET stack.

    docker compose up -d && docker compose exec web python manage.py seed_data --force
    python scripts/redis_failover_drill.py
    docker compose start <stopped node>     # afterwards: rejoins as a replica

Proves, with the real app: WebSocket chat (channel layer) and notification delivery
(Celery broker -> worker -> handler -> WS push) work before the primary dies, REST keeps
serving during the failover, the sentinels promote a replica, and realtime + Celery
recover on the new primary. Needs the `websockets` package (bundled with uvicorn[standard]).
"""

import asyncio
import json
import pathlib
import subprocess
import time
import urllib.request

import websockets

API = "http://localhost:8000/api/v1"
WS = "ws://localhost:8000/ws"
ORIGIN = "http://localhost:5173"
PASSWORD = "PleetDemo!2026"
COMPOSE_DIR = str(pathlib.Path(__file__).resolve().parent.parent)
# Fixed addresses from docker-compose.yml (the "redis" network).
NODE_BY_IP = {
    "172.28.0.10": "redis-primary",
    "172.28.0.11": "redis-replica-1",
    "172.28.0.12": "redis-replica-2",
}


def call(method, path, token=None, body=None):
    req = urllib.request.Request(f"{API}{path}", method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    data = json.dumps(body).encode() if body is not None else None
    with urllib.request.urlopen(req, data=data, timeout=10) as resp:
        raw = resp.read()
        return resp.status, (json.loads(raw) if raw else None)


def login(email):
    _, body = call("POST", "/auth/login", body={"email": email, "password": PASSWORD})
    return body["token"], body["user"]["id"]


def master():
    out = subprocess.run(
        ["docker", "compose", "exec", "-T", "sentinel-2", "redis-cli", "-p", "26379",
         "sentinel", "get-master-addr-by-name", "pleet-core"],
        capture_output=True, text=True, cwd=COMPOSE_DIR, check=True,
    )  # fmt: skip
    return out.stdout.split()[0]


async def chat_round(label, tenant_token, agent_token, thread_id):
    _, t_ticket = call("POST", "/realtime/ticket", tenant_token)
    _, a_ticket = call("POST", "/realtime/ticket", agent_token)
    headers = {"Origin": ORIGIN}
    notes_ticket = call("POST", "/realtime/ticket", agent_token)[1]["ticket"]
    async with (
        websockets.connect(
            f"{WS}/threads/{thread_id}/?ticket={t_ticket['ticket']}", additional_headers=headers
        ) as tenant_ws,
        websockets.connect(
            f"{WS}/threads/{thread_id}/?ticket={a_ticket['ticket']}", additional_headers=headers
        ) as agent_ws,
        websockets.connect(
            f"{WS}/notifications/?ticket={notes_ticket}", additional_headers=headers
        ) as agent_notes,
    ):
        text = f"[{label}] hello at {time.strftime('%H:%M:%S')}"
        await tenant_ws.send(json.dumps({"type": "message.send", "body": text}))
        got = json.loads(await asyncio.wait_for(agent_ws.recv(), timeout=10))
        assert got["type"] == "message.created" and got["message"]["body"] == text, got
        # The notification travels: outbox -> Celery broker -> worker -> handler -> WS push.
        note = json.loads(await asyncio.wait_for(agent_notes.recv(), timeout=20))
        assert note["type"] == "notification.created", note
        print(f"  {label}: chat delivered over WS; notification pushed via Celery worker")


def main():
    tenant_token, _ = login("tenant@pleet.test")
    agent_token, _ = login("agent@pleet.test")
    _, threads = call("GET", "/threads", tenant_token)
    thread_id = threads[0]["id"]

    # Whichever node is primary *now* (it moves after every drill) is the one we kill.
    original = master()
    victim = NODE_BY_IP[original]
    print(f"primary before: {original} ({victim})")
    asyncio.run(chat_round("before failover", tenant_token, agent_token, thread_id))

    print(f"stopping {victim} ...")
    subprocess.run(
        ["docker", "compose", "stop", victim], cwd=COMPOSE_DIR, check=True, capture_output=True
    )
    killed_at = time.monotonic()

    # REST must keep answering during the failover window (cache misses go to Postgres).
    status, props = call("GET", "/properties", tenant_token)
    print(f"  during failover: GET /properties -> {status}, {len(props)} rows")

    deadline = time.monotonic() + 60
    while (current := master()) == original:
        if time.monotonic() > deadline:
            raise SystemExit("FAILED: no promotion within 60s")
        time.sleep(1)
    print(f"primary after: {current} (promoted in {time.monotonic() - killed_at:.1f}s)")

    for attempt in range(30):  # clients reconnect to the new primary
        try:
            asyncio.run(chat_round("after failover", tenant_token, agent_token, thread_id))
            print(f"  realtime recovered {time.monotonic() - killed_at:.1f}s after the kill "
                  f"({attempt} retries)")  # fmt: skip
            break
        except Exception as exc:
            time.sleep(1)
            last = exc
    else:
        raise SystemExit(f"FAILED to recover: {last!r}")

    with urllib.request.urlopen("http://localhost:8000/health/ready/", timeout=5) as resp:
        print(f"readiness: {resp.read().decode()}")
    print(f"DRILL PASSED. Restore the node with: docker compose start {victim}")


if __name__ == "__main__":
    main()
