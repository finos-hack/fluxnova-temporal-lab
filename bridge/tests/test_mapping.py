import json

import pytest

from fluxnova_temporal_bridge.mapping import (
    DEFAULT_ERROR_CODE,
    TaskConfigError,
    TemporalTaskConfig,
    build_workflow_input,
    classify_workflow_failure,
    from_fluxnova_variables,
    map_workflow_result,
    to_fluxnova_variables,
    ui_url,
)


def task(**variables):
    return {
        "id": "ext-1",
        "activityId": "Task_DocumentChecks",
        "processInstanceId": "pi-42",
        "businessKey": "CUST-001",
        "retries": None,
        "variables": {
            name: {"value": value, "type": "String"} for name, value in variables.items()
        },
    }


BASE = dict(temporalWorkflowType="DocumentChecksWorkflow", temporalTaskQueue="kyc")


def test_config_defaults_use_business_key_and_activity():
    config = TemporalTaskConfig.from_task(task(**BASE))
    assert config.workflow_id == "CUST-001:Task_DocumentChecks"
    assert config.error_code == DEFAULT_ERROR_CODE
    assert config.result_variable == "temporalResult"
    assert config.input_variables == ()


def test_config_falls_back_to_instance_id_without_business_key():
    t = task(**BASE, temporalWorkflowId=":Task_DocumentChecks")
    t["businessKey"] = None
    assert TemporalTaskConfig.from_task(t).workflow_id == "pi-42:Task_DocumentChecks"


def test_config_explicit_values():
    config = TemporalTaskConfig.from_task(
        task(
            **BASE,
            temporalWorkflowId="kyc-CUST-001",
            temporalInputVariables=" customerName, country ,",
            temporalErrorCode="DOC_CHECK_FAILED",
        )
    )
    assert config.workflow_id == "kyc-CUST-001"
    assert config.input_variables == ("customerName", "country")
    assert config.error_code == "DOC_CHECK_FAILED"


def test_config_requires_type_and_queue():
    with pytest.raises(TaskConfigError, match="temporalWorkflowType"):
        TemporalTaskConfig.from_task(task(temporalTaskQueue="kyc"))
    with pytest.raises(TaskConfigError, match="temporalTaskQueue"):
        TemporalTaskConfig.from_task(task(temporalWorkflowType="X", temporalTaskQueue="  "))


def test_input_selects_listed_variables():
    t = task(**BASE, temporalInputVariables="customerName,missing", customerName="Ada", other="x")
    config = TemporalTaskConfig.from_task(t)
    assert build_workflow_input(t, config) == {"customerName": "Ada", "missing": None}


def test_input_defaults_to_all_but_config_variables():
    t = task(**BASE, customerName="Ada", temporalUiUrl="http://old")
    config = TemporalTaskConfig.from_task(t)
    assert build_workflow_input(t, config) == {"customerName": "Ada"}


def test_typed_variable_round_trip():
    typed = to_fluxnova_variables(
        {"s": "a", "b": True, "i": 7, "l": 2**40, "d": 1.5, "n": None, "o": {"k": [1]}}
    )
    assert typed["b"]["type"] == "Boolean"
    assert typed["i"]["type"] == "Integer"
    assert typed["l"]["type"] == "Long"
    assert typed["d"]["type"] == "Double"
    assert typed["n"]["type"] == "Null"
    assert typed["o"] == {"value": json.dumps({"k": [1]}), "type": "Json"}
    assert from_fluxnova_variables(typed)["o"] == {"k": [1]}


def test_result_mapping():
    config = TemporalTaskConfig.from_task(task(**BASE))
    assert map_workflow_result({"riskScore": 10}, config) == {"riskScore": 10}
    assert map_workflow_result(42, config) == {"temporalResult": 42}


class FakeAppError(Exception):
    def __init__(self, message, *details, type=None, cause=None):
        super().__init__(message)
        self.message = message
        self.details = details
        self.type = type
        self.cause = cause


class FakeWorkflowFailure(Exception):
    def __init__(self, cause):
        super().__init__("Workflow execution failed")
        self.cause = cause


def test_bpmn_error_type_sets_error_code():
    failure = FakeWorkflowFailure(
        FakeAppError("Sanctions hit", "SANCTIONS_HIT", type="BpmnError")
    )
    assert classify_workflow_failure(failure, "DEFAULT") == ("SANCTIONS_HIT", "Sanctions hit")


def test_nested_bpmn_error_from_activity_is_found():
    inner = FakeAppError("No passport", "MISSING_DOCUMENT", type="BpmnError")
    failure = FakeWorkflowFailure(FakeAppError("Activity task failed", cause=inner))
    assert classify_workflow_failure(failure, "DEFAULT")[0] == "MISSING_DOCUMENT"


def test_other_failures_use_configured_code_and_deepest_message():
    failure = FakeWorkflowFailure(FakeAppError("boom", type="ValueError"))
    assert classify_workflow_failure(failure, "DOC_CHECK_FAILED") == ("DOC_CHECK_FAILED", "boom")


def test_ui_url():
    assert (
        ui_url("http://localhost:8233/", "default", "CUST-001:T", "r1")
        == "http://localhost:8233/namespaces/default/workflows/CUST-001:T/r1/history"
    )
    assert ui_url("http://x", "ns", "w", None) == "http://x/namespaces/ns/workflows/w"
