"""Garage signing is fixed, independent of ambient or retired region settings."""

from unittest.mock import Mock
from urllib.parse import parse_qs, urlsplit

import pytest
from hamcrest import assert_that, contains_string, equal_to, is_

from api.core.config import Config
from api.domains.artifacts.buckets import BucketCredentials
from api.domains.artifacts.models import Artifact
from api.infrastructure.s3.client import ArtifactStorage


@pytest.mark.parametrize("retired_region", ["garage", "us-east-1"])
def test_storage_always_signs_for_garage(monkeypatch, retired_region):
    monkeypatch.setenv("ARTIFACT_S3_REGION", retired_region)
    monkeypatch.setenv("AWS_DEFAULT_REGION", "eu-west-1")
    config = Config.model_construct(artifact_s3_endpoint_url="http://private-garage:3900")
    buckets = Mock()
    buckets.credentials.return_value = BucketCredentials("agent-files", "GK" + "a" * 32, "b" * 64)
    artifact = Mock(spec=Artifact)
    client = ArtifactStorage(config, buckets).client(artifact)
    assert_that(client.meta.region_name, equal_to("garage"))
    query = parse_qs(
        urlsplit(
            client.generate_presigned_url(
                "get_object", Params={"Bucket": "agent-files", "Key": "fixture"}, ExpiresIn=900
            )
        ).query
    )
    assert_that(query["X-Amz-Credential"][0], contains_string("/garage/s3/aws4_request"))
    assert_that(hasattr(config, "artifact_s3_region"), is_(False))
