from uuid import uuid4

from api.domains.workflows.models import WorkflowStep


def test_step_accepts_new_and_historical_completion_criteria():
    data = {"id": str(uuid4()), "name": "Review", "goal": "Review the report"}
    assert WorkflowStep.model_validate(data).completion_criteria is None
    historical = WorkflowStep.model_validate({**data, "completion_criteria": "Risks are covered"})
    assert historical.model_dump()["completion_criteria"] == "Risks are covered"
