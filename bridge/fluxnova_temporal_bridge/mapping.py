"""Pure mapping logic between Fluxnova external tasks and Temporal workflows.

No I/O and no Temporal SDK import, so it can be unit-tested anywhere.

A "Temporal task" in BPMN is an external service task on topic ``temporal``
whose input parameters (set by the designer plugin) configure the call:

    temporalWorkflowType      required  Temporal workflow type name
    temporalTaskQueue         required  task queue the Temporal worker polls
    temporalWorkflowId        optional  default "<businessKey or instanceId>:<activityId>"
    temporalInputVariables    optional  comma-separated variables; empty = all
    temporalResultVariable    optional  variable for non-object results (default temporalResult)
    temporalErrorCode         optional  BPMN error code on workflow failure
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Iterable

TOPIC = "temporal"
BPMN_ERROR_TYPE = "BpmnError"
DEFAULT_ERROR_CODE = "TEMPORAL_WORKFLOW_FAILED"
DEFAULT_RESULT_VARIABLE = "temporalResult"

CONFIG_VARIABLES = {
    "temporalWorkflowType",
    "temporalTaskQueue",
    "temporalWorkflowId",
    "temporalInputVariables",
    "temporalResultVariable",
    "temporalErrorCode",
}
# Written back by the bridge; never sent to the workflow as input.
BRIDGE_VARIABLES = {"temporalRunId", "temporalUiUrl", "temporalErrorMessage"}

INT32_MIN, INT32_MAX = -(2**31), 2**31 - 1


class TaskConfigError(ValueError):
    """The BPMN task is missing required Temporal configuration."""


def _blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and value.strip() == "")


def from_fluxnova_variables(variables: dict[str, Any] | None) -> dict[str, Any]:
    """Convert Fluxnova typed variables ({name: {type, value}}) to plain values."""
    plain: dict[str, Any] = {}
    for name, typed in (variables or {}).items():
        if not isinstance(typed, dict):
            plain[name] = typed
            continue
        value = typed.get("value")
        if typed.get("type") == "Json" and isinstance(value, str):
            try:
                value = json.loads(value)
            except ValueError:
                pass
        plain[name] = value
    return plain


def to_fluxnova_variables(values: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Convert plain values to Fluxnova typed variables for the REST API."""
    typed: dict[str, dict[str, Any]] = {}
    for name, value in values.items():
        if value is None:
            typed[name] = {"value": None, "type": "Null"}
        elif isinstance(value, bool):
            typed[name] = {"value": value, "type": "Boolean"}
        elif isinstance(value, int):
            kind = "Integer" if INT32_MIN <= value <= INT32_MAX else "Long"
            typed[name] = {"value": value, "type": kind}
        elif isinstance(value, float):
            typed[name] = {"value": value, "type": "Double"}
        elif isinstance(value, str):
            typed[name] = {"value": value, "type": "String"}
        else:
            typed[name] = {"value": json.dumps(value), "type": "Json"}
    return typed


@dataclass(frozen=True)
class TemporalTaskConfig:
    workflow_type: str
    task_queue: str
    workflow_id: str
    input_variables: tuple[str, ...]
    result_variable: str
    error_code: str

    @classmethod
    def from_task(cls, task: dict[str, Any]) -> "TemporalTaskConfig":
        values = from_fluxnova_variables(task.get("variables"))
        workflow_type = values.get("temporalWorkflowType")
        task_queue = values.get("temporalTaskQueue")
        missing = [
            name
            for name, value in (
                ("temporalWorkflowType", workflow_type),
                ("temporalTaskQueue", task_queue),
            )
            if _blank(value)
        ]
        if missing:
            raise TaskConfigError(
                f"Task {task.get('activityId')} is missing input parameter(s): "
                + ", ".join(missing)
            )

        workflow_id = values.get("temporalWorkflowId")
        # An expression such as "${execution.processBusinessKey}:x" renders as
        # ":x" when there is no business key; fall back to the instance id.
        if _blank(workflow_id) or str(workflow_id).startswith(":"):
            base = task.get("businessKey") or task.get("processInstanceId")
            workflow_id = f"{base}:{task.get('activityId')}"

        raw_inputs = values.get("temporalInputVariables")
        inputs = tuple(
            name.strip() for name in str(raw_inputs or "").split(",") if name.strip()
        )

        return cls(
            workflow_type=str(workflow_type).strip(),
            task_queue=str(task_queue).strip(),
            workflow_id=str(workflow_id).strip(),
            input_variables=inputs,
            result_variable=str(
                values.get("temporalResultVariable") or DEFAULT_RESULT_VARIABLE
            ).strip(),
            error_code=str(values.get("temporalErrorCode") or DEFAULT_ERROR_CODE).strip(),
        )


def build_workflow_input(
    task: dict[str, Any], config: TemporalTaskConfig
) -> dict[str, Any]:
    """Select the process variables sent to the workflow as one JSON object."""
    values = from_fluxnova_variables(task.get("variables"))
    if config.input_variables:
        return {name: values.get(name) for name in config.input_variables}
    hidden = CONFIG_VARIABLES | BRIDGE_VARIABLES
    return {name: value for name, value in values.items() if name not in hidden}


def map_workflow_result(result: Any, config: TemporalTaskConfig) -> dict[str, Any]:
    """Object results are merged into the process; anything else goes in one variable."""
    if isinstance(result, dict):
        return dict(result)
    return {config.result_variable: result}


def ui_url(base_url: str, namespace: str, workflow_id: str, run_id: str | None) -> str:
    url = f"{base_url.rstrip('/')}/namespaces/{namespace}/workflows/{workflow_id}"
    return f"{url}/{run_id}/history" if run_id else url


def _cause_chain(error: BaseException | None) -> Iterable[Any]:
    seen = set()
    current: Any = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        yield current
        current = getattr(current, "cause", None) or getattr(current, "__cause__", None)


def classify_workflow_failure(
    error: BaseException, default_code: str
) -> tuple[str, str]:
    """Return (bpmn_error_code, message) for a failed or cancelled workflow.

    A workflow (or activity) raising ``ApplicationError(msg, "CODE",
    type="BpmnError")`` chooses the error code; any other failure uses the
    task's configured code so the process can still route it.
    """
    chain = list(_cause_chain(error))
    for item in chain:
        if getattr(item, "type", None) == BPMN_ERROR_TYPE:
            details = list(getattr(item, "details", None) or [])
            code = str(details[0]) if details else default_code
            return code, str(getattr(item, "message", None) or item)
    deepest = chain[-1] if chain else error
    return default_code, str(getattr(deepest, "message", None) or deepest)
