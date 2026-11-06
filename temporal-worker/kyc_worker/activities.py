"""Activities for the document-checks sub-workflow.

They simulate external systems (document store, AI extraction service,
sanctions list). The extraction activity fails on its first attempts on
purpose, so the Temporal UI shows automatic retries.
"""

from __future__ import annotations

import os
from typing import Any

from temporalio import activity

FLAKY_ATTEMPTS = int(os.environ.get("FLAKY_ATTEMPTS", "2"))

HIGH_RISK_COUNTRIES = {"IR", "KP", "SY", "RU", "BY"}
MEDIUM_RISK_COUNTRIES = {"TR", "AE", "PA", "NG", "ZA", "BR", "CN"}


@activity.defn
async def fetch_documents(application: dict[str, Any]) -> list[dict[str, Any]]:
    """Collect the documents attached to the onboarding application."""
    customer = application.get("customerName") or "Unknown customer"
    activity.logger.info("Fetching documents for %s", customer)
    return [
        {"kind": "passport", "owner": customer, "pages": 2},
        {"kind": "proof_of_address", "owner": customer, "pages": 1},
        {"kind": "source_of_funds", "owner": customer, "pages": 4},
    ]


@activity.defn
async def extract_document_data(documents: list[dict[str, Any]]) -> dict[str, Any]:
    """Pretend to run OCR / AI extraction. Fails transiently first."""
    attempt = activity.info().attempt
    if attempt <= FLAKY_ATTEMPTS:
        raise RuntimeError(
            f"Extraction service unavailable (simulated, attempt {attempt})"
        )
    owner = documents[0]["owner"] if documents else ""
    return {
        "extractedName": owner,
        "documentCount": len(documents),
        "pages": sum(d.get("pages", 0) for d in documents),
    }


@activity.defn
async def screen_sanctions(application: dict[str, Any]) -> dict[str, Any]:
    """Screen the customer against a (fake) sanctions list and score risk."""
    name = str(application.get("customerName") or "")
    country = str(application.get("country") or "").upper()
    amount = float(application.get("requestedAmount") or 0)

    hit = "sanction" in name.lower()
    score = 10
    if country in HIGH_RISK_COUNTRIES:
        score += 60
    elif country in MEDIUM_RISK_COUNTRIES:
        score += 30
    if amount > 1_000_000:
        score += 15
    elif amount > 250_000:
        score += 5
    return {"sanctionsHit": hit, "riskScore": min(score, 100)}


@activity.defn
async def release_document_hold(documents: list[dict[str, Any]]) -> None:
    """Compensation: release documents locked for this application."""
    activity.logger.info("Compensation: releasing %d documents", len(documents))
