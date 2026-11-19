from uuid import uuid4


def draft(name: str = "Weekly report") -> dict:
    return {
        "name": name,
        "description": "Prepare a weekly pipeline report",
        "steps": [
            {
                "id": str(uuid4()),
                "name": "Prepare report",
                "goal": "Summarize the pipeline",
                "completion_criteria": "A summary covers changes and risks",
            }
        ],
        "inputs": [
            {
                "key": "period",
                "label": "Reporting period",
                "description": "The period to summarize",
                "type": "text",
                "required": True,
            }
        ],
    }


def legacy_version(context, workflow_id, body: dict):
    """Store a version as it was saved before a step's output became part of its goal."""
    import json

    from sqlalchemy import text

    version_id = uuid4()
    with context.postgres_delegate.engine.begin() as connection:
        number = connection.execute(
            text("SELECT max(number) + 1 FROM workflow_version WHERE workflow_id = :id"), {"id": workflow_id}
        ).scalar_one()
        connection.execute(
            text(
                "INSERT INTO workflow_version (id, created_at, updated_at, workflow_id, number, snapshot) "
                "VALUES (:id, now(), now(), :workflow_id, :number, CAST(:snapshot AS jsonb))"
            ),
            {"id": version_id, "workflow_id": workflow_id, "number": number, "snapshot": json.dumps(body)},
        )
        connection.execute(
            text("UPDATE workflow SET revision = :number WHERE id = :id"), {"number": number, "id": workflow_id}
        )
    return version_id
