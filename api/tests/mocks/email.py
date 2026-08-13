from collections.abc import Callable
from typing import cast

from injector import Module, provider, singleton

from api.infrastructure.email.client import EmailClient
from api.infrastructure.email.models import Email
from api.infrastructure.email.service import EmailService

_BLOCKED_HOST = "api.cloudflare.com"


def make_email_blocking_post(real_post: Callable) -> Callable:
    def _guarded_post(*args, **kwargs):
        url = str(args[0] if args else kwargs.get("url", ""))
        if _BLOCKED_HOST in url:
            raise RuntimeError(
                f"Test attempted to call {_BLOCKED_HOST}. Patch "
                "api.infrastructure.email.client.httpx.post or bind MockEmailModule "
                "if this send is intentional."
            )
        return real_post(*args, **kwargs)

    return _guarded_post


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

    @singleton
    @provider
    def provide_email_service(self) -> EmailService:
        parent = self

        class MockEmailService:
            def send_password_reset_email(
                self,
                receiver_email: str,
                password_reset_link: str,
                receiver_name: str | None = None,
            ) -> bool:
                parent.emails.append(
                    Email(
                        to_email=receiver_email,
                        subject="Reset your password",
                        html_part=f'<a href="{password_reset_link}">Reset password</a>',
                    )
                )
                return True

        return cast(EmailService, MockEmailService())
