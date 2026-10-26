"""Durable asynchronous storage requests and bounded deleted-owner cleanup."""

import hmac
import logging
from dataclasses import dataclass
from uuid import UUID

from injector import inject, singleton

from api.core.config import Config
from api.domains.artifacts.buckets import ArtifactBucketRepository
from api.domains.artifacts.models import ArtifactBucket
from api.infrastructure.crypto import decrypt_token
from api.infrastructure.s3.provisioner import GarageProvisioner

logger = logging.getLogger(__name__)


@inject
@singleton
@dataclass
class ArtifactBucketProvisioner:
    buckets: ArtifactBucketRepository
    config: Config
    provider: GarageProvisioner

    def process_agent(self, agent_id: UUID, organization_id: UUID) -> None:
        row = self.buckets.status(agent_id, organization_id)
        if row is not None and row.state == "PENDING":
            self.process(row.id)

    def key_bucket(self, row: ArtifactBucket) -> str | None:
        key = self.provider.key(row.access_key)
        if key is None:
            return None
        secret = decrypt_token(row.secret_key_encrypted, self.config.agent_token_encryption_key)
        if (
            key["accessKeyId"] != row.access_key
            or key["permissions"]["createBucket"]
            or not hmac.compare_digest(key.get("secretAccessKey", ""), secret)
        ):
            raise ValueError("Unexpected bucket credential identity or authority")
        buckets = key["buckets"]
        if not buckets:
            return None
        if (
            len(buckets) != 1
            or buckets[0]["globalAliases"]
            or buckets[0]["localAliases"] != [row.name]
            or buckets[0]["permissions"] != {"read": True, "write": True, "owner": False}
        ):
            raise ValueError("Bucket credential is not isolated to its Agent")
        if row.provider_id and buckets[0]["id"] != row.provider_id:
            raise ValueError("Bucket provider identity changed")
        return buckets[0]["id"]

    def provision(self, row: ArtifactBucket) -> None:
        if self.provider.key(row.access_key) is None:
            self.provider.import_key(
                row.access_key,
                decrypt_token(row.secret_key_encrypted, self.config.agent_token_encryption_key),
                f"agent-artifacts:{row.organization_id}:{row.agent_id}",
            )
        provider_id = self.key_bucket(row)
        if provider_id is None:
            provider_id = self.provider.create_bucket(row.access_key, row.name)
        row.provider_id = provider_id
        if self.key_bucket(row) != provider_id:
            raise ValueError("Provisioned bucket permissions did not converge")
        row.state = "READY"

    def reclaim(self, row: ArtifactBucket, has_files: bool) -> None:
        row.state = "DELETING"
        # Retain the data key until every file's bytes have actually been purged.
        if has_files:
            return
        provider_id = self.key_bucket(row) or row.provider_id
        if provider_id:
            info = self.provider.bucket(provider_id)
            if info is not None:
                if (
                    info["objects"]
                    or info["unfinishedUploads"]
                    or any(key["accessKeyId"] != row.access_key for key in info["keys"])
                ):
                    raise ValueError("Refusing a nonempty or shared bucket reclamation")
                self.provider.delete_bucket(provider_id)
        self.provider.delete_key(row.access_key)
        row.state = "DELETED"
        row.secret_key_encrypted = ""

    def process(self, bucket_id: UUID) -> bool:
        try:
            with self.buckets.operation(bucket_id) as work:
                if work is None:
                    return False
                row = work.bucket
                if work.owner_deleted:
                    self.reclaim(row, work.has_files)
                elif row.state == "PENDING":
                    self.provision(row)
                elif row.state == "DELETING":
                    raise ValueError("Deleted bucket owner unexpectedly became live")
                return row.state == "READY"
        except Exception as exc:
            logger.warning("Bucket operation %s will retry (%s)", bucket_id, type(exc).__name__)
            return False

    def run(self, limit: int = 100) -> int:
        if not self.config.artifact_s3_endpoint_url:
            return 0
        return sum(self.process(bucket_id) for bucket_id in self.buckets.due(limit))
