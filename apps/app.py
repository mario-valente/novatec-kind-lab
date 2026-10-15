import logging
import os
import time
from contextlib import contextmanager

import redis
import requests
from flask import Flask, Response, jsonify, request
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest

ROLE = os.environ["APP_ROLE"]
CLUSTER = os.environ.get("CLUSTER", "novatec-lab")
if ROLE not in {"app-a", "app-b"}:
    raise ValueError("APP_ROLE must be app-a or app-b")

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(ROLE)
labels = ("cluster", "source", "target", "journey", "tenant")
calls = Counter("lab_calls_total", "Observed dependency calls", (*labels, "status"))
duration = Histogram(
    "lab_call_duration_seconds",
    "Client-observed dependency duration",
    labels,
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2, 5),
)
last_seen = Gauge("lab_edge_last_seen_seconds", "Last actual call on a journey edge", labels)
cache = redis.Redis(host="redis", socket_timeout=2, socket_connect_timeout=2)


@contextmanager
def observe(target, journey, tenant):
    values = (CLUSTER, ROLE, target, journey, tenant)
    start = time.monotonic()
    status = "ok"
    try:
        yield
    except Exception:
        status = "error"
        raise
    finally:
        calls.labels(*values, status).inc()
        duration.labels(*values).observe(time.monotonic() - start)
        last_seen.labels(*values).set(time.time())
        logger.info("source=%s target=%s journey=%s tenant=%s status=%s", ROLE, target, journey, tenant, status)


def parameters():
    tenant = request.headers.get("X-Tenant", "tenant-a")
    scenario = request.args.get("scenario", "normal")
    if tenant not in {"tenant-a", "tenant-b"} or scenario not in {"normal", "error"}:
        return None
    return tenant, scenario


@app.get("/healthz")
def health():
    return jsonify(status="ok", service=ROLE)


@app.get("/metrics")
def metrics():
    return Response(generate_latest(), content_type=CONTENT_TYPE_LATEST)


@app.get("/whatsapp")
@app.get("/notify")
def entry():
    if ROLE != "app-a":
        return jsonify(error="entrypoint is app-a"), 404
    params = parameters()
    if params is None:
        return jsonify(error="invalid tenant or scenario"), 400
    tenant, scenario = params
    journey = "whatsapp_inbound" if request.path == "/whatsapp" else "active_notification"
    try:
        with observe("app-b", journey, tenant):
            response = requests.get(
                "http://app-b:8080/handle",
                params={"scenario": scenario},
                headers={"X-Journey": journey, "X-Tenant": tenant},
                timeout=5,
            )
            response.raise_for_status()
            body = response.json()
    except (requests.RequestException, ValueError):
        logger.exception("dependency failed journey=%s tenant=%s", journey, tenant)
        return jsonify(error="app-b failed", journey=journey, tenant=tenant), 502
    return jsonify(journey=journey, tenant=tenant, flow=body["flow"], count=body.get("count"))


@app.get("/handle")
def handle():
    if ROLE != "app-b":
        return jsonify(error="handler is app-b"), 404
    params = parameters()
    journey = request.headers.get("X-Journey")
    if params is None or journey not in {"whatsapp_inbound", "active_notification"}:
        return jsonify(error="invalid tenant, scenario or journey"), 400
    tenant, scenario = params
    time.sleep(0.03 if journey == "whatsapp_inbound" else 0.16)
    if scenario == "error":
        logger.error("intentional failure journey=%s tenant=%s", journey, tenant)
        return jsonify(error="intentional failure"), 503
    if journey == "active_notification":
        return jsonify(flow=["app-a", "app-b"])
    try:
        with observe("redis", journey, tenant):
            count = cache.incr(f"lab:{tenant}:whatsapp")
    except redis.RedisError:
        logger.exception("redis failed tenant=%s", tenant)
        return jsonify(error="redis failed"), 503
    return jsonify(flow=["app-a", "app-b", "redis"], count=count)
