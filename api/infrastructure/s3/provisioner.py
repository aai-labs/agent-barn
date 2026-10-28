"""Garage control-plane access, used by API provisioning and operator cleanup."""

from typing import Any

import httpx
from injector import inject, singleton

from api.core.config import Config


@inject
@singleton
class GarageProvisioner:
    def __init__(self, config: Config):
        self.origin = config.artifact_provisioner_url.rstrip("/")
        self.token = config.artifact_provisioner_token

    def request(
        self, operation: str, *, method: str = "POST", params: dict | None = None, body: dict | None = None
    ) -> dict[str, Any] | None:
        if not self.origin or not self.token:
            raise ValueError("Private Garage provisioning is not configured")
        with httpx.Client(timeout=15, trust_env=False, follow_redirects=False) as client:
            response = client.request(
                method,
                self.origin + "/v2/" + operation,
                params=params,
                json=body,
                headers={"Authorization": "Bearer " + self.token},
            )
        if response.status_code == 404 and method == "GET":
            return None
        if response.status_code != 200:
            raise OSError(f"Garage {operation} failed (HTTP {response.status_code})")
        return response.json()

    def key(self, access_key: str) -> dict[str, Any] | None:
        return self.request("GetKeyInfo", method="GET", params={"id": access_key, "showSecretKey": "true"})

    def import_key(self, access_key: str, secret_key: str, name: str) -> None:
        self.request("ImportKey", body={"accessKeyId": access_key, "secretAccessKey": secret_key, "name": name})

    def create_bucket(self, access_key: str, name: str) -> str:
        response = self.request(
            "CreateBucket",
            body={
                "localAlias": {
                    "accessKeyId": access_key,
                    "alias": name,
                    "allow": {"read": True, "write": True, "owner": False},
                }
            },
        )
        if response is None:
            raise ValueError("Garage returned no bucket identity")
        return response["id"]

    def bucket(self, provider_id: str) -> dict[str, Any] | None:
        return self.request("GetBucketInfo", method="GET", params={"id": provider_id})

    def delete_bucket(self, provider_id: str) -> None:
        if self.bucket(provider_id) is not None:
            self.request("DeleteBucket", params={"id": provider_id})

    def delete_key(self, access_key: str) -> None:
        if self.key(access_key) is not None:
            self.request("DeleteKey", params={"id": access_key})
