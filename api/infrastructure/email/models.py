from dataclasses import dataclass


@dataclass
class EmailTemplateAttribute:
    name: str
    value: str | dict


@dataclass
class EmailTemplate:
    file_name: str
    subject: str
    attributes: list[EmailTemplateAttribute]
    receiver_email: str
    receiver_name: str | None


@dataclass
class Email:
    to_email: str
    subject: str
    html_part: str
    from_name: str | None = "Agent Barn"
    text_part: str | None = None
    from_email: str | None = None
    reply_to: str | None = None
    headers: dict[str, str] | None = None
