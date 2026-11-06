"""Runs the Temporal worker for the KYC document-checks workflow."""

from __future__ import annotations

import asyncio
import logging
import os

from temporalio.client import Client
from temporalio.worker import Worker

from . import activities
from .workflows import TASK_QUEUE, DocumentChecksWorkflow

log = logging.getLogger("kyc-worker")


async def connect(address: str, namespace: str) -> Client:
    delay = 1.0
    while True:
        try:
            return await Client.connect(address, namespace=namespace)
        except Exception as exc:  # server not up yet
            log.info("Temporal not reachable at %s (%s); retrying", address, exc)
            await asyncio.sleep(delay)
            delay = min(delay * 2, 10)


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    client = await connect(
        os.environ.get("TEMPORAL_ADDRESS", "localhost:7233"),
        os.environ.get("TEMPORAL_NAMESPACE", "default"),
    )
    worker = Worker(
        client,
        task_queue=TASK_QUEUE,
        workflows=[DocumentChecksWorkflow],
        activities=[
            activities.fetch_documents,
            activities.extract_document_data,
            activities.screen_sanctions,
            activities.release_document_hold,
        ],
    )
    log.info("Worker polling task queue %s", TASK_QUEUE)
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
