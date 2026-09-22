"""The master key cache must not be a constructor parameter.

Annotated as a plain dataclass field it became one, so injector supplied "" —
not None, so the cache "hit" on an empty key, the Kubernetes Secret was never
read, and every privileged call went out as `Authorization: Bearer `. Agent
creation died on "LiteLLM key generation failed; cannot create agent".

Constructing through the injector is the only thing that reproduces it: every
other test builds the client positionally, where the default applies correctly.
"""

import base64
from unittest.mock import MagicMock, patch

from hamcrest import assert_that, equal_to

from api.core.utils import create_injector
from api.infrastructure.litellm.client import LiteLLMClient


def _injected_client() -> LiteLLMClient:
    return create_injector().get(LiteLLMClient)


def _secret(value: bytes = b"sk-master") -> MagicMock:
    return MagicMock(data={"LITELLM_MASTER_KEY": base64.b64encode(value).decode()})


def test_the_injector_does_not_populate_the_cache():
    assert_that(_injected_client()._cached_master_key, equal_to(None))


def test_an_injected_client_reads_the_secret_and_sends_a_usable_header():
    client = _injected_client()
    with patch.object(client.k8s, "get_secret", return_value=_secret()) as get_secret:
        header = client._headers(client._master_key())["Authorization"]
    assert_that(get_secret.called, equal_to(True))
    assert_that(header, equal_to("Bearer sk-master"))


def test_the_secret_is_still_read_only_once():
    """The caching this guards is why the field exists; losing it would put a
    Kubernetes round-trip back on every call."""
    client = _injected_client()
    with patch.object(client.k8s, "get_secret", return_value=_secret()) as get_secret:
        client._master_key()
        client._master_key()
        client._master_key()
    assert_that(get_secret.call_count, equal_to(1))
