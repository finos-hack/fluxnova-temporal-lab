"""Fluxnova -> Temporal bridge.

Long-polls Fluxnova for external tasks on topic ``temporal``. For each task it:

1. starts (or re-attaches to) a Temporal workflow whose id is derived from the
   business key, so a retried task never starts a second run;
2. records the workflow id and a Temporal UI link on the process instance;
3. keeps the Fluxnova lock alive while the workflow runs, and cancels the
   workflow if the Fluxnova task disappears (process cancelled or migrated);
4. completes the task with the workflow result, raises a BPMN error when the
   workflow fails, or reports a technical failure (Cockpit incident) when
   Temporal itself cannot be reached.
"""

from __future__ import annotations

import asyncio
import logging
import os
import socket
import traceback
from typing import Any

from temporalio.client import Client, WorkflowFailureError, WorkflowHandle
from temporalio.common import WorkflowIDConflictPolicy, WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError

from .fluxnova import FluxnovaClient, TaskGone
from .mapping import (
    TOPIC,
    TaskConfigError,
    TemporalTaskConfig,
    build_workflow_input,
    classify_workflow_failure,
    map_workflow_result,
    to_fluxnova_variables,
    ui_url,
)

log = logging.getLogger("bridge")

FLUXNOVA_URL = os.environ.get("FLUXNOVA_REST_URL", "http://localhost:8080/engine-rest")
TEMPORAL_ADDRESS = os.environ.get("TEMPORAL_ADDRESS", "localhost:7233")
TEMPORAL_NAMESPACE = os.environ.get("TEMPORAL_NAMESPACE", "default")
TEMPORAL_UI_URL = os.environ.get("TEMPORAL_UI_URL", "http://localhost:8233")
MAX_CONCURRENT = int(os.environ.get("BRIDGE_MAX_CONCURRENT_TASKS", "20"))
LOCK_MS = int(os.environ.get("BRIDGE_LOCK_MS", "30000"))
LONG_POLL_MS = int(os.environ.get("BRIDGE_LONG_POLL_MS", "20000"))
FAILURE_RETRY_MS = int(os.environ.get("BRIDGE_FAILURE_RETRY_MS", "10000"))


class Bridge:
    def __init__(self, fluxnova: FluxnovaClient, temporal: Client) -> None:
        self.fluxnova = fluxnova
        self.temporal = temporal
        self.slots = asyncio.Semaphore(MAX_CONCURRENT)
        self.running: set[asyncio.Task[None]] = set()

    async def run(self) -> None:
        log.info("Polling %s for topic '%s'", FLUXNOVA_URL, TOPIC)
        while True:
            free = MAX_CONCURRENT - len(self.running)
            if free <= 0:
                await asyncio.sleep(0.5)
                continue
            try:
                tasks = await self.fluxnova.fetch_and_lock(TOPIC, free, LONG_POLL_MS)
            except Exception as exc:  # engine starting or restarting
                log.info("Fluxnova not reachable (%s); retrying", exc)
                await asyncio.sleep(3)
                continue
            for task in tasks:
                job = asyncio.create_task(self.handle(task))
                self.running.add(job)
                job.add_done_callback(self.running.discard)

    async def handle(self, task: dict[str, Any]) -> None:
        task_id = task["id"]
        try:
            config = TemporalTaskConfig.from_task(task)
        except TaskConfigError as exc:
            log.error("%s", exc)
            await self._fail(task, str(exc), "", retries=0)
            return

        try:
            handle = await self._start(task, config)
        except Exception as exc:
            log.exception("Could not start workflow %s", config.workflow_id)
            await self._fail(task, f"Temporal unavailable: {exc}", traceback.format_exc())
            return

        run_id = handle.result_run_id or handle.run_id
        link = ui_url(TEMPORAL_UI_URL, TEMPORAL_NAMESPACE, config.workflow_id, run_id)
        audit = {
            "temporalWorkflowId": config.workflow_id,
            "temporalRunId": run_id,
            "temporalUiUrl": link,
        }
        await self.fluxnova.set_process_variables(
            task["processInstanceId"], to_fluxnova_variables(audit)
        )
        log.info("Task %s -> workflow %s (%s)", task["activityId"], config.workflow_id, link)

        result_job = asyncio.create_task(handle.result())
        try:
            while True:
                done, _ = await asyncio.wait({result_job}, timeout=LOCK_MS / 3000)
                if done:
                    break
                try:
                    await self.fluxnova.extend_lock(task_id)
                except TaskGone:
                    log.warning(
                        "Fluxnova task %s is gone; cancelling workflow %s",
                        task_id,
                        config.workflow_id,
                    )
                    try:
                        await handle.cancel()
                    except Exception as exc:
                        log.warning("Cancel of %s failed: %s", config.workflow_id, exc)
                    return
                except Exception as exc:
                    log.warning("Could not extend lock on %s: %s", task_id, exc)

            try:
                result = result_job.result()
            except WorkflowFailureError as failure:
                code, message = classify_workflow_failure(failure, config.error_code)
                log.info("Workflow %s failed -> BPMN error %s", config.workflow_id, code)
                variables = dict(audit, temporalErrorMessage=message)
                await self.fluxnova.bpmn_error(
                    task_id, code, message, to_fluxnova_variables(variables)
                )
                return

            variables = map_workflow_result(result, config)
            variables.update(audit)
            await self.fluxnova.complete(task_id, to_fluxnova_variables(variables))
            log.info("Workflow %s completed; task %s done", config.workflow_id, task_id)
        except TaskGone:
            log.warning("Task %s disappeared before it could be closed", task_id)
        except Exception as exc:
            log.exception("Unexpected error on task %s", task_id)
            await self._fail(task, str(exc), traceback.format_exc())
        finally:
            if not result_job.done():
                result_job.cancel()

    async def _start(self, task: dict[str, Any], config: TemporalTaskConfig) -> WorkflowHandle:
        arg = build_workflow_input(task, config)
        try:
            return await self.temporal.start_workflow(
                config.workflow_type,
                arg,
                id=config.workflow_id,
                task_queue=config.task_queue,
                # Re-run only if the previous run failed; attach if still running.
                id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY,
                id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
                memo={
                    "fluxnovaProcessInstanceId": task.get("processInstanceId"),
                    "fluxnovaActivityId": task.get("activityId"),
                    "fluxnovaBusinessKey": task.get("businessKey"),
                },
            )
        except WorkflowAlreadyStartedError:
            # A previous run already completed: reuse its result (exactly-once).
            log.info("Workflow %s already completed; reusing its result", config.workflow_id)
            return self.temporal.get_workflow_handle(config.workflow_id)

    async def _fail(
        self, task: dict[str, Any], message: str, details: str, retries: int | None = None
    ) -> None:
        if retries is None:
            current = task.get("retries")
            retries = (3 if current is None else current) - 1
        try:
            await self.fluxnova.failure(task["id"], message, details, retries, FAILURE_RETRY_MS)
        except Exception:
            log.exception("Could not report failure for task %s", task["id"])


async def connect_temporal() -> Client:
    delay = 1.0
    while True:
        try:
            return await Client.connect(TEMPORAL_ADDRESS, namespace=TEMPORAL_NAMESPACE)
        except Exception as exc:
            log.info("Temporal not reachable at %s (%s); retrying", TEMPORAL_ADDRESS, exc)
            await asyncio.sleep(delay)
            delay = min(delay * 2, 10)


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    worker_id = os.environ.get("BRIDGE_WORKER_ID", f"temporal-bridge-{socket.gethostname()}")
    temporal = await connect_temporal()
    fluxnova = FluxnovaClient(FLUXNOVA_URL, worker_id, LOCK_MS)
    try:
        await Bridge(fluxnova, temporal).run()
    finally:
        await fluxnova.close()


if __name__ == "__main__":
    asyncio.run(main())
