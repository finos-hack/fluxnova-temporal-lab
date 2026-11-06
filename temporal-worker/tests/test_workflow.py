"""Workflow tests with Temporal's time-skipping test server.

Run inside the worker image:  docker compose run --rm temporal-worker pytest -q
(the test server binary is downloaded on first run).
"""

import uuid

import pytest
from temporalio.client import WorkflowFailureError
from temporalio.exceptions import ApplicationError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from kyc_worker import activities
from kyc_worker.workflows import BPMN_ERROR_TYPE, DocumentChecksWorkflow

ALL_ACTIVITIES = [
    activities.fetch_documents,
    activities.extract_document_data,
    activities.screen_sanctions,
    activities.release_document_hold,
]


async def _run(application):
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue="test",
            workflows=[DocumentChecksWorkflow],
            activities=ALL_ACTIVITIES,
        ):
            return await env.client.execute_workflow(
                DocumentChecksWorkflow.run,
                application,
                id=f"test-{uuid.uuid4()}",
                task_queue="test",
            )


@pytest.mark.asyncio
async def test_clean_customer_returns_risk_score():
    result = await _run(
        {"customerName": "Ada Lovelace", "country": "FR", "requestedAmount": 250000}
    )
    assert result["documentsVerified"] is True
    assert result["sanctionsHit"] is False
    assert result["riskScore"] == 10


@pytest.mark.asyncio
async def test_sanctioned_customer_raises_bpmn_error():
    with pytest.raises(WorkflowFailureError) as info:
        await _run({"customerName": "Ivan Sanctioned", "country": "FR"})
    cause = info.value.cause
    assert isinstance(cause, ApplicationError)
    assert cause.type == BPMN_ERROR_TYPE
    assert cause.details[0] == "SANCTIONS_HIT"
