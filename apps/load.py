import time

import requests

i = 0
while True:
    for tenant in ("tenant-a", "tenant-b"):
        for endpoint in ("whatsapp", "notify"):
            i += 1
            scenario = "error" if i % 23 == 0 else "normal"
            expected = 502 if scenario == "error" else 200
            try:
                result = requests.get(
                    f"http://app-a:8080/{endpoint}",
                    headers={"X-Tenant": tenant},
                    params={"scenario": scenario},
                    timeout=8,
                )
                print(f"{tenant} {endpoint} status={result.status_code} expected={expected}", flush=True)
                if result.status_code != expected:
                    print(f"ERROR: unexpected response: {result.text}", flush=True)
            except requests.RequestException as exc:
                print(f"ERROR: {exc}", flush=True)
            time.sleep(0.2)
