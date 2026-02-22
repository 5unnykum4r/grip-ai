"""Tests for the workflow engine models."""

from __future__ import annotations

from grip.workflow.models import StepDef, StepResult, StepStatus, WorkflowDef


def test_workflow_validation_passes():
    wf = WorkflowDef(
        name="test",
        steps=[
            StepDef(name="a", prompt="do A"),
            StepDef(name="b", prompt="do B", depends_on=["a"]),
        ],
    )
    assert wf.validate() == []


def test_workflow_validation_missing_dep():
    wf = WorkflowDef(
        name="test",
        steps=[
            StepDef(name="a", prompt="do A", depends_on=["nonexistent"]),
        ],
    )
    errors = wf.validate()
    assert len(errors) == 1
    assert "nonexistent" in errors[0]


def test_workflow_validation_cycle():
    wf = WorkflowDef(
        name="test",
        steps=[
            StepDef(name="a", prompt="A", depends_on=["b"]),
            StepDef(name="b", prompt="B", depends_on=["a"]),
        ],
    )
    errors = wf.validate()
    assert any("Circular" in e for e in errors)


def test_execution_order_parallel():
    wf = WorkflowDef(
        name="test",
        steps=[
            StepDef(name="a", prompt="A"),
            StepDef(name="b", prompt="B"),
            StepDef(name="c", prompt="C", depends_on=["a", "b"]),
        ],
    )
    layers = wf.get_execution_order()
    assert len(layers) == 2
    assert set(layers[0]) == {"a", "b"}
    assert layers[1] == ["c"]


def test_execution_order_sequential():
    wf = WorkflowDef(
        name="test",
        steps=[
            StepDef(name="a", prompt="A"),
            StepDef(name="b", prompt="B", depends_on=["a"]),
            StepDef(name="c", prompt="C", depends_on=["b"]),
        ],
    )
    layers = wf.get_execution_order()
    assert len(layers) == 3
    assert layers[0] == ["a"]
    assert layers[1] == ["b"]
    assert layers[2] == ["c"]


def test_step_result_lifecycle():
    result = StepResult(name="test_step")
    assert result.status == StepStatus.PENDING

    result.mark_running()
    assert result.status == StepStatus.RUNNING
    assert result.started_at is not None

    result.mark_completed("output text", iterations=3)
    assert result.status == StepStatus.COMPLETED
    assert result.output == "output text"
    assert result.iterations == 3


def test_step_result_failure():
    result = StepResult(name="fail_step")
    result.mark_running()
    result.mark_failed("something broke")
    assert result.status == StepStatus.FAILED
    assert result.error == "something broke"


def test_workflow_to_dict_roundtrip():
    wf = WorkflowDef(
        name="roundtrip",
        description="Test roundtrip",
        steps=[
            StepDef(name="s1", prompt="step 1", profile="researcher"),
            StepDef(name="s2", prompt="step 2 using {{s1.output}}", depends_on=["s1"]),
        ],
    )
    data = wf.to_dict()
    restored = WorkflowDef.from_dict(data)
    assert restored.name == "roundtrip"
    assert len(restored.steps) == 2
    assert restored.steps[1].depends_on == ["s1"]
