from uuid import UUID

from fastapi import HTTPException, status


class UserAlreadyPartOfOrganizationException(Exception):
    def __init__(self, user_id: UUID | None, organization_id: UUID):
        self.user_id = user_id
        self.organization_id = organization_id
        super().__init__(
            f"User with id {user_id if user_id else 'None'} is already part of organization with id {organization_id}"
        )


class OneOwnerPerOrganizationException(HTTPException):
    def __init__(self, organization_id: UUID):
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Organization with id {organization_id} already has an owner",
        )
