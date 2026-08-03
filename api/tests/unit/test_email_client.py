from email.message import Message
from unittest.mock import MagicMock

from api.infrastructure.email.client import LOGO_CONTENT_ID, EmailClient
from api.infrastructure.email.models import Email


def _client() -> EmailClient:
    return EmailClient(config=MagicMock())


def _image_parts(msg: Message) -> list[Message]:
    return [p for p in msg.walk() if p.get_content_maintype() == "image"]


def test_build_message_embeds_logo_as_inline_cid_when_referenced():
    html = f'<img src="cid:{LOGO_CONTENT_ID}" alt="Agent Barn" />'
    email = Email(to_email="a@example.com", subject="Hi", html_part=html)

    msg = _client()._build_message(email, "no-reply@example.com")

    # multipart/related so the inline image binds to the html part.
    assert msg.get_content_subtype() == "related"

    images = _image_parts(msg)
    assert len(images) == 1
    logo = images[0]
    assert logo.get_content_type() == "image/png"
    # Content-ID must match the cid: referenced in the html (angle-bracket wrapped).
    assert logo["Content-ID"] == f"<{LOGO_CONTENT_ID}>"
    assert logo.get("Content-Disposition", "").startswith("inline")
    assert logo.get_payload(decode=True)  # non-empty image bytes


def test_build_message_omits_logo_when_not_referenced():
    email = Email(
        to_email="a@example.com",
        subject="Hi",
        html_part="<p>no logo here</p>",
    )

    msg = _client()._build_message(email, "no-reply@example.com")

    assert _image_parts(msg) == []
