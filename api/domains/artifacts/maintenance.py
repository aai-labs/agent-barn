"""Bounded operator-only cleanup; intentionally no product route."""

from api.core.utils import create_injector
from api.domains.artifacts.service import ArtifactService


def main() -> None:
    injector = create_injector()
    print(f"Purged {injector.get(ArtifactService).purge()} artifacts")


if __name__ == "__main__":
    main()
