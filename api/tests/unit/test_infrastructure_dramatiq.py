from uuid import uuid4

from api.infrastructure.dramatiq import first_arg_as_uuid


def test_first_arg_as_uuid_parses_leading_message_arg():
    delivery_id = uuid4()

    assert first_arg_as_uuid({"args": [str(delivery_id), {"source": "test"}]}) == delivery_id
    assert first_arg_as_uuid({"args": []}) is None
    assert first_arg_as_uuid({"args": ["not-a-uuid"]}) is None
