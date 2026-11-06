"""End-to-end check of the lab, run against the live stack:

    docker compose exec bridge python -m fluxnova_temporal_bridge.smoke

Starts three KYC instances, completes the human "Analyst review" task, and
checks where each one ends up once Temporal has done the document checks.
"""

from __future__ import annotations

import os
import sys
import time
import uuid

import httpx

REST = os.environ.get("FLUXNOVA_REST_URL", "http://localhost:8080/engine-rest")
TIMEOUT_S = 120

SCENARIOS = [
    # name, variables, expected end/wait activity, expected variables
    ("clean customer is approved",
     {"customerName": "Ada Lovelace", "country": "FR", "requestedAmount": 250000},
     "End_AccountOpened", {"creditDecision": "APPROVE", "riskScore": 10, "documentsVerified": True}),
    ("high-risk country is rejected",
     {"customerName": "Boris Example", "country": "RU", "requestedAmount": 50000},
     "End_Rejected", {"creditDecision": "REJECT", "riskScore": 70}),
    ("sanctions hit raises a BPMN error",
     {"customerName": "Ivan Sanctioned", "country": "FR", "requestedAmount": 1000},
     "Task_ComplianceException", {"documentCheckError": "SANCTIONS_HIT"}),
]


def typed(values):
    out = {}
    for k, v in values.items():
        out[k] = {"value": v, "type": "Long" if isinstance(v, int) else "String"}
    return out


def wait_for(fn, what):
    deadline = time.time() + TIMEOUT_S
    while time.time() < deadline:
        try:
            result = fn()
        except httpx.HTTPError:
            result = None
        if result:
            return result
        time.sleep(1.5)
    raise AssertionError(f"timed out waiting for {what}")


def run(http: httpx.Client, name, variables, target, expected) -> bool:
    key = f"SMOKE-{uuid.uuid4().hex[:6]}"
    instance = http.post(
        "/process-definition/key/kyc-onboarding/start",
        json={"businessKey": key, "variables": typed(variables)},
    ).raise_for_status().json()
    pid = instance["id"]

    task = wait_for(
        lambda: http.get("/task", params={"processInstanceId": pid, "taskDefinitionKey": "Task_AnalystReview"}).json(),
        "Analyst review task",
    )[0]
    http.post(f"/task/{task['id']}/complete", json={"variables": {}}).raise_for_status()

    wait_for(
        lambda: http.get(
            "/history/activity-instance",
            params={"processInstanceId": pid, "activityId": target},
        ).json(),
        f"activity {target}",
    )

    found = {
        v["name"]: v.get("value")
        for v in http.get("/history/variable-instance", params={"processInstanceId": pid}).json()
    }
    wrong = {k: (found.get(k), v) for k, v in expected.items() if found.get(k) != v}
    ok = not wrong and str(found.get("temporalUiUrl", "")).startswith("http")
    print(f"[{'PASS' if ok else 'FAIL'}] {name}  ({key} -> {target})")
    if wrong:
        print(f"       unexpected (got, want): {wrong}")
    if ok:
        print(f"       Temporal: {found.get('temporalUiUrl')}")
    return ok


def main() -> int:
    with httpx.Client(base_url=REST, timeout=30) as http:
        wait_for(lambda: http.get("/process-definition/key/kyc-onboarding").status_code == 200,
                 "the kyc-onboarding process to be deployed")
        results = [run(http, *scenario) for scenario in SCENARIOS]
    print(f"{sum(results)}/{len(results)} scenarios passed")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
