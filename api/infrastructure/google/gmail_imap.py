"""Read-only Gmail access over IMAP with a Google app password.

An app password unlocks the whole mailbox, so read-only is enforced here rather than by
Google: the inbox is only ever opened with EXAMINE (``readonly=True``), messages are only
fetched with ``BODY.PEEK`` so reading never marks them seen, and this module issues no
STORE, COPY, MOVE, EXPUNGE or APPEND command, and never connects to SMTP.

The gateway is shared by every Organization, so each call is bounded: a listing fetches
only the newest messages, a search covers only the newest ``SEARCH_WINDOW`` messages,
and a message larger than ``MAX_FETCH_BYTES`` is read only from its start.
"""

import email
import imaplib
import re
import ssl
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from email.message import EmailMessage
from email.policy import default as default_policy
from html.parser import HTMLParser

GMAIL_IMAP_HOST = "imap.gmail.com"
GMAIL_IMAP_PORT = 993
MAX_LIST_LIMIT = 50
MAX_QUERY_LENGTH = 500
#: A search's UIDs come back on one line, which imaplib refuses past 1 MB, so only the
#: newest messages are searched. 50,000 eight-digit UIDs stay well under that.
SEARCH_WINDOW = 50_000
MAX_FETCH_BYTES = 2_000_000
_MAILBOX = "INBOX"
_TIMEOUT_SECONDS = 20
_MAX_BODY_CHARS = 50_000
_UID = re.compile(rb"UID (\d+)")
_SIZE = re.compile(rb"UID (\d+) RFC822\.SIZE (\d+)")
_MESSAGE_ID = re.compile(r"[0-9]{1,20}")
_HEADERS = "(UID BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])"


class MailSignInFailed(Exception):
    """Gmail rejected the address or app password."""


class MailUnavailable(Exception):
    """Gmail could not be reached or answered unexpectedly."""


class MailNotFound(Exception):
    """No inbox message with that id."""


class InvalidMailQuery(ValueError):
    """A search that is too long or carries control characters."""


@dataclass(frozen=True)
class MailSummary:
    id: str
    sender: str
    subject: str
    date: str


@dataclass(frozen=True)
class MailMessage:
    id: str
    sender: str
    to: str
    cc: str
    subject: str
    date: str
    body: str
    truncated: bool
    attachments: list[str] = field(default_factory=list)


class GmailInbox:
    """Reads one Gmail inbox for the credential gateway. Holds no state between calls."""

    def list_messages(self, address: str, app_password: str, *, query: str | None, limit: int) -> list[MailSummary]:
        """Newest-first headers of inbox messages, optionally filtered with Gmail search syntax."""
        search = _search_literal(query) if query else None
        limit = max(1, min(limit, MAX_LIST_LIMIT))
        with _inbox(address, app_password) as (conn, exists):
            if exists == 0:
                return []
            if search is None:
                # The newest messages by position: no SEARCH, so no inbox is too big to list.
                status, data = conn.fetch(f"{max(1, exists - limit + 1)}:{exists}", _HEADERS)
            else:
                # A literal carries any UTF-8 search; imaplib sends command arguments as ASCII.
                # imaplib sends the literal as bytes; typeshed declares the attribute str.
                conn.literal = search  # ty: ignore[invalid-assignment]
                window = f"{max(1, exists - SEARCH_WINDOW + 1)}:*"
                status, data = conn.uid("SEARCH", "CHARSET", "UTF-8", window, "X-GM-RAW")
                if status != "OK":
                    raise MailUnavailable("search failed")
                uids = (data[0] or b"").split()[-limit:]
                if not uids:
                    return []
                status, data = conn.uid("FETCH", b",".join(uids).decode(), _HEADERS)
            if status != "OK":
                raise MailUnavailable("fetch failed")
        summaries = []
        for uid, raw in _fetched(data):
            headers = email.message_from_bytes(raw, policy=default_policy)
            summaries.append(
                MailSummary(
                    id=uid,
                    sender=str(headers.get("From", "")),
                    subject=str(headers.get("Subject", "")),
                    date=str(headers.get("Date", "")),
                )
            )
        return sorted(summaries, key=lambda s: int(s.id), reverse=True)

    def get_message(self, address: str, app_password: str, message_id: str) -> MailMessage:
        """One inbox message's headers and readable text, left unread."""
        if _MESSAGE_ID.fullmatch(message_id) is None:
            raise MailNotFound(message_id)
        with _inbox(address, app_password) as (conn, _):
            status, data = conn.uid("FETCH", message_id, "(UID RFC822.SIZE)")
            if status != "OK":
                raise MailUnavailable("fetch failed")
            size = _size(data, message_id)
            if size is None:
                raise MailNotFound(message_id)
            clipped = size > MAX_FETCH_BYTES
            item = f"BODY.PEEK[]<0.{MAX_FETCH_BYTES}>" if clipped else "BODY.PEEK[]"
            status, data = conn.uid("FETCH", message_id, f"(UID {item})")
            if status != "OK":
                raise MailUnavailable("fetch failed")
        raw = next((body for uid, body in _fetched(data) if uid == message_id), None)
        if raw is None:
            raise MailNotFound(message_id)
        message = email.message_from_bytes(raw, policy=default_policy)
        assert isinstance(message, EmailMessage)
        body = _readable_body(message)
        return MailMessage(
            id=message_id,
            sender=str(message.get("From", "")),
            to=str(message.get("To", "")),
            cc=str(message.get("Cc", "")),
            subject=str(message.get("Subject", "")),
            date=str(message.get("Date", "")),
            body=body[:_MAX_BODY_CHARS],
            truncated=clipped or len(body) > _MAX_BODY_CHARS,
            attachments=[part.get_filename() or "attachment" for part in message.iter_attachments()],
        )


def check_sign_in(address: str, app_password: str) -> None:
    """Sign in and out again; raises when Gmail refuses or cannot be reached."""
    conn = _connect()
    try:
        _login(conn, address, app_password)
    finally:
        _logout(conn)


@contextmanager
def _inbox(address: str, app_password: str) -> Iterator[tuple[imaplib.IMAP4_SSL, int]]:
    """A signed-in connection with the inbox opened read-only (EXAMINE), and its message count."""
    conn = _connect()
    try:
        _login(conn, address, app_password)
        try:
            status, data = conn.select(_MAILBOX, readonly=True)
        except (OSError, imaplib.IMAP4.error) as exc:
            raise MailUnavailable("could not open the inbox") from exc
        count = data[0] if status == "OK" and data else None
        if not isinstance(count, bytes) or not count.isdigit():
            raise MailUnavailable("could not open the inbox")
        try:
            yield conn, int(count)
        except (OSError, imaplib.IMAP4.error) as exc:
            raise MailUnavailable("Gmail stopped responding") from exc
    finally:
        _logout(conn)


def _connect() -> imaplib.IMAP4_SSL:
    # imaplib's own default context checks neither the certificate nor the hostname, so a
    # server posing as Gmail would be handed the app password. Verify both before LOGIN.
    context = ssl.create_default_context()
    try:
        return imaplib.IMAP4_SSL(GMAIL_IMAP_HOST, GMAIL_IMAP_PORT, ssl_context=context, timeout=_TIMEOUT_SECONDS)
    except OSError as exc:
        raise MailUnavailable("could not reach Gmail") from exc


def _login(conn: imaplib.IMAP4_SSL, address: str, app_password: str) -> None:
    try:
        conn.login(address, app_password)
    except imaplib.IMAP4.error as exc:
        raise MailSignInFailed() from exc
    except OSError as exc:
        raise MailUnavailable("Gmail stopped responding") from exc


def _logout(conn: imaplib.IMAP4_SSL) -> None:
    try:
        conn.logout()
    except OSError, imaplib.IMAP4.error:
        pass


def _fetched(data: list) -> Iterator[tuple[str, bytes]]:
    """(uid, bytes) pairs from a UID FETCH response."""
    for part in data:
        if isinstance(part, tuple):
            match = _UID.search(part[0])
            if match is not None:
                yield match.group(1).decode(), part[1]


def _size(data: list, message_id: str) -> int | None:
    """The size a UID FETCH of RFC822.SIZE reported for one message, if Gmail has it."""
    for part in data:
        match = _SIZE.search(part if isinstance(part, bytes) else b"")
        if match is not None and match.group(1).decode() == message_id:
            return int(match.group(2))
    return None


def _search_literal(query: str) -> bytes:
    """A search as the UTF-8 bytes of an IMAP literal. Control characters are refused
    so a search reads as one plain Gmail query."""
    if len(query) > MAX_QUERY_LENGTH or any(ord(c) < 32 or ord(c) == 127 for c in query):
        raise InvalidMailQuery("Invalid search query")
    return query.encode("utf-8")


def _readable_body(message: EmailMessage) -> str:
    part = message.get_body(preferencelist=("plain", "html"))
    if part is None:
        return ""
    try:
        content = part.get_content()
    except LookupError, UnicodeError:
        # A charset Python does not know: anyone can send one, so read it as best we can.
        payload = part.get_payload(decode=True)
        content = payload.decode("utf-8", errors="replace") if isinstance(payload, bytes) else ""
    if part.get_content_type() == "text/html":
        return _html_to_text(content)
    return content


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.chunks: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style"}:
            self._skip += 1
        elif tag in {"br", "p", "div", "tr", "li"}:
            self.chunks.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"} and self._skip:
            self._skip -= 1

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self.chunks.append(data)


def _html_to_text(html: str) -> str:
    parser = _TextExtractor()
    parser.feed(html)
    return re.sub(r"\n{3,}", "\n\n", "".join(parser.chunks)).strip()
