"""List stored Agent Secrets and Shared Credentials that no longer pass validation.

Every start re-validates decrypted provider content, so tightening a provider's schema can
stop Agents whose stored content predates the rule. Run this inside the ``agentbarn-api``
pod before deploying such a change. It is read-only and prints identifiers, providers, and
validation messages, never secret values.

Example::

    python -m api.scripts.check_secret_contents
"""

from __future__ import annotations

import json

from pydantic import ValidationError
from sqlmodel import Session, col, select

from api.core.config import get_config
from api.domains.agents.models import AgentSecret, SecretProvider, validate_content
from api.domains.shared_credentials.models import SharedCredential
from api.infrastructure.crypto import decrypt_token
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate


def _problem(provider: str, ciphertext: str, key: str) -> str | None:
    """Why this content would fail at start, or None when it validates."""
    try:
        raw = json.loads(decrypt_token(ciphertext, key))
        validate_content(SecretProvider(provider), raw)
    except ValidationError as error:
        return "; ".join(f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in error.errors(include_input=False))
    except Exception as error:
        # Report undecryptable or unknown rows instead of stopping the scan.
        return f"{type(error).__name__}"
    return None


def run() -> int:
    config = get_config()
    key = config.agent_token_encryption_key
    delegate = PostgresRepositoryDelegate(config)
    checked = failing = 0
    with Session(delegate.engine) as session:
        for secret in session.exec(select(AgentSecret).where(col(AgentSecret.content).is_not(None))):
            if secret.content is None:
                continue
            checked += 1
            if problem := _problem(secret.provider, secret.content, key):
                failing += 1
                print(f"agent_secret {secret.id} (agent {secret.agent_id}, {secret.provider}): {problem}")
        for credential in session.exec(select(SharedCredential)):
            checked += 1
            if problem := _problem(credential.provider, credential.content, key):
                failing += 1
                print(
                    f"shared_credential {credential.id} (organization {credential.organization_id}, {credential.provider}): {problem}"
                )
    print(f"Checked {checked} stored credential(s); {failing} would fail validation.")
    return 1 if failing else 0


def main() -> None:
    raise SystemExit(run())


if __name__ == "__main__":
    main()
