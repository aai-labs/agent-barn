from enum import StrEnum

from pydantic import BaseModel as PydanticBaseModel


class SyncProviderCapability(StrEnum):
    LOCATION_PICKER = "location_picker"
    ADMIN_APPROVAL = "admin_approval"


class SyncProviderDescriptorRead(PydanticBaseModel):
    """What the settings list shows for one provider. Never credentials or provider data."""

    key: str
    display_name: str
    tagline: str
    folder_hint: str
    schema_version: int
    capabilities: list[SyncProviderCapability]
