"""Service-only S3 access. No object keys or bucket credentials come from callers."""

import base64
import binascii
import hashlib
import re
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError
from urllib.parse import quote, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, build_opener

import boto3
from botocore.config import Config as S3Config
from injector import inject, singleton

from api.core.config import Config
from api.domains.artifacts.buckets import ArtifactBucketRepository
from api.domains.artifacts.models import Artifact
from api.domains.artifacts.storage import ArtifactDownload, DownloadDenied
from api.domains.artifacts.storage import ArtifactStorage as ArtifactStorageContract


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> None:
        return None


@inject
@singleton
@dataclass
class ArtifactStorage(ArtifactStorageContract):
    config: Config
    buckets: ArtifactBucketRepository

    def client(self, artifact: Artifact) -> Any:
        credentials = self.buckets.credentials(artifact)
        return boto3.client(
            "s3",
            endpoint_url=self.config.artifact_s3_endpoint_url or None,
            region_name="garage",
            aws_access_key_id=credentials.access_key,
            aws_secret_access_key=credentials.secret_key,
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
        self.client(artifact).put_object(
            Bucket=artifact.bucket,
            Key=artifact.object_key,
            Body=content,
            ContentType=artifact.content_type,
            Metadata={"sha256": artifact.checksum},
        )
        # Verify bytes at the actual storage boundary rather than trusting an ETag.
        response = self.client(artifact).get_object(Bucket=artifact.bucket, Key=artifact.object_key)
        digest = hashlib.sha256()
        size = 0
        with response["Body"] as stream:
            while chunk := stream.read(64 * 1024):
                size += len(chunk)
                if size > artifact.size:
                    raise ValueError("Stored artifact failed integrity verification")
                digest.update(chunk)
        if size != artifact.size or digest.hexdigest() != artifact.checksum:
            raise ValueError("Stored artifact failed integrity verification")

    def issue_download(self, artifact: Artifact, seconds: int) -> str:
        signed = self.client(artifact).generate_presigned_url(
            "get_object",
            Params={
                "Bucket": artifact.bucket,
                "Key": artifact.object_key,
                "ResponseContentDisposition": "attachment; filename*=UTF-8''" + quote(artifact.filename, safe=""),
                "ResponseContentType": "application/octet-stream",
            },
            ExpiresIn=seconds,
        )
        # Transport only the provider's signed query; never expose its private
        # origin/bucket/key, or issue a second application-managed capability.
        return base64.urlsafe_b64encode(urlsplit(signed).query.encode()).decode()

    def download(self, artifact: Artifact, access: str) -> ArtifactDownload:
        try:
            query = base64.b64decode(access, altchars=b"-_", validate=True).decode("ascii")
        except ValueError, binascii.Error, UnicodeError:
            raise DownloadDenied from None
        if not query or not re.fullmatch(r"[A-Za-z0-9._~!$&'()*+,;=:@/?%\-]+", query):
            raise DownloadDenied
        # Derive the upstream origin/path only from service config and persisted
        # metadata. Callers supply opaque authority, never a proxy target URL.
        target = urlsplit(
            self.client(artifact).generate_presigned_url(
                "get_object", Params={"Bucket": artifact.bucket, "Key": artifact.object_key}, ExpiresIn=1
            )
        )
        url = urlunsplit(target._replace(query=query))
        try:
            response = build_opener(ProxyHandler({}), _NoRedirect()).open(url, timeout=30)
        except ValueError:
            raise DownloadDenied from None
        except HTTPError as exc:
            status = exc.code
            exc.close()
            if status in {400, 401, 403, 404}:
                raise DownloadDenied from None
            raise OSError("Private artifact storage unavailable") from None
        if response.status != 200 or response.headers.get("Content-Length") != str(artifact.size):
            response.close()
            raise OSError("Private artifact storage returned an invalid response")

        def chunks() -> Iterator[bytes]:
            remaining = artifact.size
            try:
                while remaining:
                    chunk = response.read(min(64 * 1024, remaining))
                    if not chunk:
                        raise OSError("Incomplete artifact download")
                    remaining -= len(chunk)
                    yield chunk
            finally:
                response.close()

        return ArtifactDownload(artifact.filename, artifact.size, chunks(), response.close)

    def delete(self, artifact: Artifact) -> None:
        self.client(artifact).delete_object(Bucket=artifact.bucket, Key=artifact.object_key)
