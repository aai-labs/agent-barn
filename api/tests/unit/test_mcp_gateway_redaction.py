"""The MCP gateway's redaction of a credential a server echoes back, however it is escaped."""

import json

import pytest
from hamcrest import assert_that, contains_string, equal_to, is_not

from api.domains.mcp_servers.gateway import redact

SECRET = 'Bearer secret"quoted\\token'


@pytest.mark.parametrize(
    "answer",
    [
        pytest.param(("plain " + SECRET + " end").encode(), id="raw bytes"),
        pytest.param(json.dumps({"text": "called with " + SECRET}).encode(), id="JSON-escaped"),
        pytest.param(b'{"t": "\\u0042earer secret\\"quoted\\\\token"}', id="unicode-escaped"),
        pytest.param(b'data: {"t": "' + json.dumps(SECRET).encode()[1:-1] + b'"}', id="an SSE data line"),
    ],
)
def test_the_credential_is_redacted_whatever_its_escaping(answer: bytes):
    redacted = redact(answer, [SECRET.encode()])

    assert_that(redacted.decode(), is_not(contains_string("quoted")))
    assert_that(redacted.decode(), contains_string("[REDACTED]"))


def test_an_answer_without_the_credential_is_left_byte_for_byte():
    answer = b'data: {"jsonrpc":"2.0","result":{"path":"a\\\\b","note":"line\\nbreak"}}'

    assert_that(redact(answer, [SECRET.encode()]), equal_to(answer))
