"""Service-only S3 access. No object keys or bucket credentials come from callers."""

import hashlib
from dataclasses import dataclass
from functools import cached_property
from typing import Any
from urllib.parse import quote

import boto3
from botocore.config import Config as S3Config
from injector import inject, singleton

from api.core.config import Config
from api.domains.artifacts.models import Artifact


@inject
@singleton
@dataclass
class ArtifactStorage:
    config: Config

    def client(self) -> Any:
        return self._client

    @cached_property
    def _client(self) -> Any:
        return boto3.client(
            "s3",
            endpoint_url=self.config.artifact_s3_endpoint_url or None,
            region_name=self.config.artifact_s3_region,
            aws_access_key_id=self.config.artifact_s3_access_key or None,
            aws_secret_access_key=self.config.artifact_s3_secret_key or None,
            config=S3Config(
                request_checksum_calculation="when_required",
                response_checksum_validation="when_required",
                signature_version="s3v4",
                s3={"addressing_style": "path"},
                retries={"max_attempts": 2},
                connect_timeout=5,
                read_timeout=30,
            ),
        )

    def put(self, artifact: Artifact, content: bytes) -> None:
        # Garage does not enforce conditional Put. Only the locked, checksum-bound
        # UPLOADING transaction may call this; READY objects never take this path.
        self.client().put_object(
            Bucket=artifact.bucket,
            Key=artifact.object_key,
            Body=content,
            ContentType=artifact.content_type,
            Metadata={"sha256": artifact.checksum},
        )
        # Verify bytes at the actual storage boundary rather than trusting an ETag.
        response = self.client().get_object(Bucket=artifact.bucket, Key=artifact.object_key)
        with response["Body"] as stream:
            stored = stream.read(artifact.size + 1)
        if len(stored) != artifact.size or hashlib.sha256(stored).hexdigest() != artifact.checksum:
            raise ValueError("Stored artifact failed integrity verification")

    def link(self, artifact: Artifact, seconds: int) -> str:
        return self.client().generate_presigned_url(
            "get_object",
            Params={
                "Bucket": artifact.bucket,
                "Key": artifact.object_key,
                "ResponseContentDisposition": "attachment; filename*=UTF-8''" + quote(artifact.filename, safe=""),
                "ResponseContentType": "application/octet-stream",
            },
            ExpiresIn=seconds,
        )

    def delete(self, artifact: Artifact) -> None:
        self.client().delete_object(Bucket=artifact.bucket, Key=artifact.object_key)
