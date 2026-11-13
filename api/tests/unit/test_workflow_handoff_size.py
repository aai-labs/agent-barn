from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest

from api.core.config import Config
from api.domains.workflows.repository import WorkflowConflict
from api.domains.workflows.runtime_service import WorkflowRuntimeService


def test_handoff_counts_instructions_before_returning_an_oversized_prompt():
    repository = Mock()
    repository.admit.return_value = (SimpleNamespace(runtime="hermes"), None, {"files": [], "text": "x" * 63900})
    service = WorkflowRuntimeService(
        repository=repository, config=Mock(spec=Config, artifact_s3_endpoint_url=""), dispatcher=Mock()
    )
    with pytest.raises(WorkflowConflict, match="context"):
        service.handoff(uuid4(), "token")
