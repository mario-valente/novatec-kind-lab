import json
import sys
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from build_dashboard import expressions

BASE = "http://127.0.0.1:3000"


def get(url, headers=None, expected=200):
    try:
        result = urlopen(Request(url, headers=headers or {}), timeout=15)
    except HTTPError as error:
        if error.code != expected:
            raise
        result = error
    with result:
        assert result.status == expected
        return json.load(result)


def prom(query, timestamp):
    data = get(BASE + "/api/datasources/proxy/uid/lab-prometheus/api/v1/query?"
               + urlencode({"query": query, "time": timestamp}))
    assert data["status"] == "success", data
    return data["data"]["result"]


def render(query, journey, tenant, timestamp):
    for variable, value in {
        "${cluster:regex}": "novatec-lab",
        "${tenant:regex}": tenant,
        "${journey:regex}": journey,
        "$__rate_interval": "1m",
        "$__range": "15m",
        "${__from}": str(int((timestamp - 900) * 1000)),
    }.items():
        query = query.replace(variable, value)
    return query


for tenant in ("tenant-a", "tenant-b"):
    for endpoint, flow in (
        ("whatsapp", ["app-a", "app-b", "redis"]),
        ("notify", ["app-a", "app-b"]),
    ):
        body = get(f"http://127.0.0.1:8082/{endpoint}", {"X-Tenant": tenant})
        assert body["flow"] == flow
        assert body["tenant"] == tenant
get("http://127.0.0.1:8082/whatsapp", {"X-Tenant": "invalid"}, 400)
get("http://127.0.0.1:8082/notify?scenario=error", expected=502)
print("PASS: real app flows, tenant propagation, invalid input and intentional failure")

deadline = time.monotonic() + 90
while True:
    timestamp = time.time()
    ready = prom('count(count by (journey, tenant) (lab_calls_total{source="app-a"}))', timestamp)
    if ready and float(ready[0]["value"][1]) == 4:
        break
    if time.monotonic() >= deadline:
        raise AssertionError("Missing Prometheus data for all journeys and tenants")
    time.sleep(5)


def values(strict, journey, tenant, index=1):
    rows = prom(render(expressions(strict)[index], journey, tenant, timestamp), timestamp)
    return {
        (row["metric"]["source"], row["metric"]["target"]): float(row["value"][1])
        for row in rows
    }


for tenant in ("tenant-a", "tenant-b"):
    normal = values(True, "whatsapp_inbound", tenant)
    active = values(True, "active_notification", tenant)
    all_journeys = values(True, ".*", tenant)
    global_normal = values(False, "whatsapp_inbound", tenant)
    global_active = values(False, "active_notification", tenant)
    assert set(normal) == {("app-a", "app-b"), ("app-b", "redis")}
    assert set(active) == {("app-a", "app-b")}
    assert set(global_normal) == set(normal)
    assert set(global_active) == set(active)
    shared = ("app-a", "app-b")
    assert active[shared] > normal[shared] + 70
    assert normal[shared] < global_normal[shared] < active[shared]
    assert abs(global_normal[shared] - global_active[shared]) < 0.001
    assert abs(all_journeys[shared] - global_normal[shared]) < 0.001
    assert values(True, "does_not_exist", tenant) == {}
    assert values(False, "does_not_exist", tenant) == {}
    print(f"PASS {tenant}: normal={normal[shared]:.2f}ms "
          f"active={active[shared]:.2f}ms aggregate={global_normal[shared]:.2f}ms")

assert values(True, ".*", "does_not_exist") == {}
print("PASS: label filtering, true journey metrics, global metrics with filtered topology and empty selectors")
