"""Temporal workflow that implements one Fluxnova task: "Document checks"."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ApplicationError

with workflow.unsafe.imports_passed_through():
    from . import activities

TASK_QUEUE = "kyc-document-checks"

# Raising an ApplicationError with this type tells the Fluxnova bridge to
# throw a BPMN error (first detail = error code) instead of a technical failure.
BPMN_ERROR_TYPE = "BpmnError"

RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=1),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(seconds=10),
    maximum_attempts=5,
)


@workflow.defn(name="DocumentChecksWorkflow")
class DocumentChecksWorkflow:
    """Fetch documents, extract data, wait for the sanctions list, screen.

    Input: the process variables sent by Fluxnova (customerName, country,
    requestedAmount). Output: a dict merged back into the process variables.
    """

    def __init__(self) -> None:
        self._stage = "starting"

    @workflow.query
    def stage(self) -> str:
        return self._stage

    @workflow.run
    async def run(self, application: dict[str, Any]) -> dict[str, Any]:
        self._stage = "fetching documents"
        documents = await workflow.execute_activity(
            activities.fetch_documents,
            application,
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=RETRY,
        )

        try:
            self._stage = "extracting data"
            extracted = await workflow.execute_activity(
                activities.extract_document_data,
                documents,
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=RETRY,
            )

            # Durable timer: survives worker and server restarts.
            self._stage = "waiting for sanctions list refresh"
            await workflow.sleep(timedelta(seconds=5))

            self._stage = "screening"
            screening = await workflow.execute_activity(
                activities.screen_sanctions,
                application,
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=RETRY,
            )

            if screening["sanctionsHit"]:
                raise ApplicationError(
                    f"Sanctions hit for {application.get('customerName')}",
                    "SANCTIONS_HIT",
                    type=BPMN_ERROR_TYPE,
                    non_retryable=True,
                )
        except (Exception, asyncio.CancelledError):
            # Saga: undo what was done before re-raising the failure.
            self._stage = "compensating"
            await workflow.execute_activity(
                activities.release_document_hold,
                documents,
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=RETRY,
            )
            raise

        self._stage = "done"
        return {
            "documentsVerified": True,
            "documentCount": extracted["documentCount"],
            "extractedName": extracted["extractedName"],
            "riskScore": screening["riskScore"],
            "sanctionsHit": False,
        }
