"""Operator-only repair of legacy shared documents and their derived observations."""

import argparse
import json
from urllib.parse import quote
from uuid import UUID

from api.infrastructure.hindsight.client import HindsightClient


def retag_shared_documents(client: HindsightClient, organization_id: UUID, *, batch_size: int = 100) -> int:
    """Replace legacy Agent access tags with authorship through Hindsight's API.

    Updating document tags invalidates derived observations and reconsolidates them.
    No memory text is changed or logged. Agents cannot reach this endpoint.
    """
    if not 1 <= batch_size <= 100:
        raise ValueError("Invalid repair batch size.")
    bank = f"/v1/default/banks/org-{organization_id}"
    offset = changed = 0
    while True:
        body = json.loads(
            client.request(
                "GET",
                bank + "/documents",
                None,
                params=[
                    ("tags", "scope:team"),
                    ("tags_match", "any_strict"),
                    ("limit", str(batch_size)),
                    ("time_field", "created_at"),
                    ("offset", str(offset)),
                ],
            ).content
        )
        documents = body["items"]
        if not isinstance(documents, list) or len(documents) > batch_size:
            raise ValueError("Invalid shared document page.")
        if not documents:
            return changed
        for document in documents:
            tags = document["tags"]
            if not isinstance(tags, list) or not all(isinstance(tag, str) for tag in tags) or "scope:team" not in tags:
                raise ValueError("Document outside shared scope.")
            legacy = [tag for tag in tags if tag.startswith("agent:")]
            if not legacy:
                continue
            if len(legacy) != 1:
                raise ValueError("Shared document has ambiguous authorship.")
            author = UUID(legacy[0].removeprefix("agent:"))
            if not document["id"].startswith(f"agent:{author}:team:"):
                raise ValueError("Shared document is outside the gateway namespace.")
            new_tags = [tag for tag in tags if tag != legacy[0]]
            new_tags.append(f"author:{author}")
            result = client.request("PATCH", bank + "/documents/" + quote(document["id"], safe=""), {"tags": new_tags})
            if json.loads(result.content).get("success") is not True:
                raise ValueError("Backend did not confirm shared document retagging.")
            changed += 1
        offset += len(documents)


def main() -> None:
    from api.core.config import Config

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("organization_id", type=UUID)
    args = parser.parse_args()
    count = retag_shared_documents(
        HindsightClient(Config(secret_signing_key="", platform_admin_credentials="")), args.organization_id
    )
    print(f"Retagged {count} shared documents.")


if __name__ == "__main__":
    main()
