"""Minimal async client for the Fluxnova external task REST API."""

from __future__ import annotations

import logging
from typing import Any

import httpx

log = logging.getLogger("bridge.fluxnova")


class TaskGone(Exception):
    """The external task no longer exists or is no longer locked by us."""


class FluxnovaClient:
    def __init__(self, base_url: str, worker_id: str, lock_ms: int) -> None:
        self._http = httpx.AsyncClient(base_url=base_url.rstrip("/"), timeout=60)
        self.worker_id = worker_id
        self.lock_ms = lock_ms

    async def close(self) -> None:
        await self._http.aclose()

    async def fetch_and_lock(
        self, topic: str, max_tasks: int, long_poll_ms: int
    ) -> list[dict[str, Any]]:
        response = await self._http.post(
            "/external-task/fetchAndLock",
            json={
                "workerId": self.worker_id,
                "maxTasks": max_tasks,
                "usePriority": True,
                "asyncResponseTimeout": long_poll_ms,
                "topics": [{"topicName": topic, "lockDuration": self.lock_ms}],
            },
            timeout=long_poll_ms / 1000 + 30,
        )
        response.raise_for_status()
        return response.json()

    async def extend_lock(self, task_id: str) -> None:
        await self._post(
            f"/external-task/{task_id}/extendLock",
            {"workerId": self.worker_id, "newDuration": self.lock_ms},
        )

    async def complete(self, task_id: str, variables: dict[str, Any]) -> None:
        await self._post(
            f"/external-task/{task_id}/complete",
            {"workerId": self.worker_id, "variables": variables},
        )

    async def bpmn_error(
        self, task_id: str, code: str, message: str, variables: dict[str, Any]
    ) -> None:
        await self._post(
            f"/external-task/{task_id}/bpmnError",
            {
                "workerId": self.worker_id,
                "errorCode": code,
                "errorMessage": message,
                "variables": variables,
            },
        )

    async def failure(
        self, task_id: str, message: str, details: str, retries: int, retry_ms: int
    ) -> None:
        await self._post(
            f"/external-task/{task_id}/failure",
            {
                "workerId": self.worker_id,
                "errorMessage": message[:600],
                "errorDetails": details,
                "retries": max(retries, 0),
                "retryTimeout": retry_ms,
            },
        )

    async def set_process_variables(
        self, process_instance_id: str, variables: dict[str, Any]
    ) -> None:
        response = await self._http.post(
            f"/process-instance/{process_instance_id}/variables",
            json={"modifications": variables},
        )
        if response.status_code >= 400:
            log.warning(
                "Could not set variables on %s: %s", process_instance_id, response.text
            )

    async def _post(self, path: str, body: dict[str, Any]) -> None:
        response = await self._http.post(path, json=body)
        if response.status_code in (400, 404, 500) and _is_gone(response):
            raise TaskGone(response.text)
        response.raise_for_status()


def _is_gone(response: httpx.Response) -> bool:
    text = response.text.lower()
    return response.status_code == 404 or "not found" in text or "does not exist" in text or "locked by" in text
