from injector import Module, provider, singleton
from typing import cast

from api.infrastructure.email.client import EmailClient
from api.infrastructure.email.models import Email


class MockEmailModule(Module):
    def __init__(self) -> None:
        self.emails: list[Email] = []

    @singleton
    @provider
    def provide_email_client(self) -> EmailClient:
        parent = self

        class MockEmailClient:
            def send(self, email: Email) -> Email:
                parent.emails.append(email)
                return email

        return cast(EmailClient, MockEmailClient())
