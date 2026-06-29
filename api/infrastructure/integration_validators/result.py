from dataclasses import dataclass, field


@dataclass
class IntegrationValidationResult:
    valid: bool
    identity: str | None = None
    missing_scopes: list[str] = field(default_factory=list)
    error: str | None = None
