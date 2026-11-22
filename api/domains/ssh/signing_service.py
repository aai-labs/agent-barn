"""Per-connection authorization, policy fencing and durable signing audit."""

import base64
import hashlib
from dataclasses import dataclass
from typing import Self
from uuid import UUID, uuid4

from fastapi import HTTPException
from injector import inject, singleton

from api.core.config import Config
from api.domains.ssh.models import SshCredential, SshRuntimeCredential
from api.domains.ssh.protocol import EXTENSION, FAILURE, SIGN, validate_request
from api.domains.ssh.repository import SshRepository, token_digest
from api.domains.ssh.signer import OpenSshSigner


@dataclass(frozen=True)
class SigningResult:
    payload: bytes
    outcome: str | None = None


class SshSigningSession:
    def __init__(
        self,
        repository: SshRepository,
        digest: str,
        state: SshRuntimeCredential,
        keys: list[SshCredential],
        signer: OpenSshSigner,
    ) -> None:
        self.repository = repository
        self.digest = digest
        self.state = state
        self.signer = signer
        self.snapshot = [(key.id, key.revision) for key in keys]
        self.host_fingerprint: str | None = None

    @property
    def agent_id(self) -> UUID:
        return self.state.agent_id

    def __enter__(self) -> Self:
        self.signer.__enter__()
        return self

    def exchange(self, data: bytes) -> SigningResult:
        current, keys = self.repository.authorize(self.digest)
        if current.generation != self.state.generation or [(key.id, key.revision) for key in keys] != self.snapshot:
            raise HTTPException(403, "SSH signing authority changed")
        try:
            operation, blob = validate_request(data)
        except ValueError:
            return SigningResult(FAILURE)
        request_id = uuid4()
        key = self.signer.key_for_blob(blob) if operation == SIGN and blob else None
        if operation == SIGN:
            self.repository.record_signing(self.state, key, "authorized", request_id, self.host_fingerprint)
        response = self.signer.exchange(data)
        if operation == EXTENSION and response == b"\x06" and blob:
            self.host_fingerprint = "SHA256:" + base64.b64encode(hashlib.sha256(blob).digest()).decode().rstrip("=")
        outcome = None
        if operation == SIGN:
            outcome = "issued" if response[0] == 14 else "refused"
            self.repository.record_signing(self.state, key, outcome, request_id, self.host_fingerprint)
        return SigningResult(response, outcome)

    def close(self) -> None:
        self.signer.close()

    def __exit__(self, *args) -> None:
        self.close()


@inject
@singleton
@dataclass
class SshSigningService:
    repository: SshRepository
    config: Config

    def session(self, token: str) -> SshSigningSession:
        digest = token_digest(token)
        state, keys = self.repository.authorize(digest)
        signer = OpenSshSigner(keys, self.config.agent_token_encryption_key, self.config.ssh_socket_directory)
        return SshSigningSession(self.repository, digest, state, keys, signer)
