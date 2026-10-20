"""Read-only Gmail over IMAP: what the gateway sends to Gmail on an agent's behalf.

A fake IMAP connection records every command, so these tests prove the reader only
ever opens the inbox read-only and only fetches with BODY.PEEK.
"""

import imaplib
import re
import socket
import ssl
import threading
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from pathlib import Path
from unittest.mock import patch

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID
from hamcrest import assert_that, contains_string, empty, equal_to, is_

from api.infrastructure.google import gmail_imap
from api.infrastructure.google.gmail_imap import (
    GmailInbox,
    InvalidMailQuery,
    MailNotFound,
    MailSignInFailed,
    MailUnavailable,
)

_READ_ONLY_COMMANDS = {"login", "select", "fetch", "uid", "logout"}


def _raw(subject: str, *, sender="Alice <alice@example.com>", html: str | None = None, attachment=False) -> bytes:
    message = EmailMessage()
    message["From"] = sender
    message["To"] = "someone@gmail.com"
    message["Subject"] = subject
    message["Date"] = "Thu, 16 Oct 2026 07:41:00 +0000"
    message.set_content("Plain body for " + subject)
    if html is not None:
        message.add_alternative(html, subtype="html")
    if attachment:
        message.add_attachment(b"%PDF", maintype="application", subtype="pdf", filename="invoice.pdf")
    return message.as_bytes()


class FakeIMAP:
    """Answers like imaplib.IMAP4_SSL for a small inbox and records each command.

    ``exists`` overrides the message count EXAMINE reports, to stand in for a large inbox.
    A search records the literal imaplib would send after the command line.
    """

    def __init__(self, messages: dict[int, bytes], *, login_error: bool = False, exists: int | None = None):
        self.messages = messages
        self.login_error = login_error
        self.exists = len(messages) if exists is None else exists
        self.commands: list[tuple] = []
        self.literal: bytes | None = None

    def login(self, user, password):
        self.commands.append(("login", user, password))
        if self.login_error:
            raise imaplib.IMAP4.error("[AUTHENTICATIONFAILED] Invalid credentials")
        return "OK", [b"Logged in"]

    def select(self, mailbox="INBOX", readonly=False):
        self.commands.append(("select", mailbox, readonly))
        return "OK", [str(self.exists).encode()]

    def fetch(self, message_set, query):
        """FETCH by message sequence number: 1 is the oldest inbox message."""
        self.commands.append(("fetch", message_set, query))
        first, last = (int(n) for n in message_set.split(":"))
        uids = sorted(self.messages)
        return "OK", self._parts(uids[first - 1 : last], query)

    def uid(self, command, *args):
        if command == "SEARCH":
            self.commands.append(("uid", command, *args, self.literal))
            self.literal = None
            return "OK", [b" ".join(str(uid).encode() for uid in sorted(self.messages))]
        self.commands.append(("uid", command, *args))
        if command == "FETCH":
            uid_set, query = args
            return "OK", self._parts([int(u) for u in uid_set.split(",") if int(u) in self.messages], query)
        raise AssertionError(f"unexpected UID command {command}")

    def _parts(self, uids: list[int], query: str) -> list:
        parts: list = []
        for uid in uids:
            raw = self.messages[uid]
            if query == "(UID RFC822.SIZE)":
                parts.append(f"{uid} (UID {uid} RFC822.SIZE {len(raw)})".encode())
                continue
            partial = re.search(r"<0\.(\d+)>", query)
            body = raw.split(b"\n\n", 1)[0] if "HEADER.FIELDS" in query else raw
            body = body[: int(partial[1])] if partial else body
            parts.append((f"{uid} (UID {uid} BODY[] {{{len(body)}}}".encode(), body))
            parts.append(b")")
        return parts

    def logout(self):
        self.commands.append(("logout",))
        return "BYE", []

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        raise AssertionError(f"the reader must not call IMAP {name}")


def _inbox(fake: FakeIMAP):
    return patch.object(gmail_imap.imaplib, "IMAP4_SSL", return_value=fake)


def _fetches(fake: FakeIMAP) -> list[str]:
    return [c[-1] for c in fake.commands if c[0] == "fetch" or c[:2] == ("uid", "FETCH")]


def _assert_read_only(fake: FakeIMAP):
    assert_that({c[0] for c in fake.commands} <= _READ_ONLY_COMMANDS, is_(True))
    assert_that([c for c in fake.commands if c[0] == "select"], equal_to([("select", "INBOX", True)]))
    for query in _fetches(fake):
        # BODY[] and a bare RFC822 mark a message read; only PEEK and the size do not.
        assert_that("BODY[" in query or re.search(r"RFC822(?!\.SIZE)", query) is not None, is_(False), query)
    assert_that(fake.commands[-1], equal_to(("logout",)))


def test_list_returns_newest_first_and_never_changes_the_mailbox():
    fake = FakeIMAP({1: _raw("first"), 2: _raw("second"), 3: _raw("third")})
    with _inbox(fake) as connect:
        messages = GmailInbox().list_messages("someone@gmail.com", "secret", query=None, limit=2)

    connect.assert_called_once()
    assert_that(connect.call_args.args, equal_to(("imap.gmail.com", 993)))
    assert_that(connect.call_args.kwargs["timeout"], equal_to(20))
    context = connect.call_args.kwargs["ssl_context"]
    assert_that((context.verify_mode, context.check_hostname), equal_to((ssl.CERT_REQUIRED, True)))
    assert_that([m.id for m in messages], equal_to(["3", "2"]))
    assert_that(messages[0].subject, equal_to("third"))
    assert_that(messages[0].sender, equal_to("Alice <alice@example.com>"))
    assert_that(fake.commands[0], equal_to(("login", "someone@gmail.com", "secret")))
    _assert_read_only(fake)


def test_listing_a_huge_inbox_fetches_only_the_newest_messages_without_searching():
    # SEARCH ALL returns every UID on one line, which imaplib refuses past 1 MB, so
    # a mailbox of a few hundred thousand messages could otherwise never be listed.
    fake = FakeIMAP({uid: _raw(f"m{uid}") for uid in range(1, 4)}, exists=3)
    with _inbox(fake):
        GmailInbox().list_messages("someone@gmail.com", "secret", query=None, limit=2)

    assert_that([c for c in fake.commands if c[:2] == ("uid", "SEARCH")], equal_to([]))
    assert_that(
        [c for c in fake.commands if c[0] == "fetch"],
        equal_to([("fetch", "2:3", "(UID BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])")]),
    )


def test_a_search_is_sent_as_a_utf8_literal_over_the_newest_messages():
    fake = FakeIMAP({1: _raw("hello")}, exists=80_000)
    with _inbox(fake):
        GmailInbox().list_messages("someone@gmail.com", "secret", query='from:José "a\\b"', limit=5)

    searches = [c for c in fake.commands if c[:2] == ("uid", "SEARCH")]
    assert_that(
        searches,
        equal_to([("uid", "SEARCH", "CHARSET", "UTF-8", "30001:*", "X-GM-RAW", 'from:José "a\\b"'.encode())]),
    )
    _assert_read_only(fake)


def test_a_search_of_a_small_inbox_covers_all_of_it():
    fake = FakeIMAP({1: _raw("hello")})
    with _inbox(fake):
        GmailInbox().list_messages("someone@gmail.com", "secret", query="from:alice", limit=5)

    assert_that([c[4] for c in fake.commands if c[:2] == ("uid", "SEARCH")], equal_to(["1:*"]))


@pytest.mark.parametrize("query", ["x\r\nA1 STORE 1 +FLAGS (\\Deleted)", "x\nfoo", "x\x00", "q" * 501])
def test_a_query_that_could_add_imap_commands_is_refused_before_connecting(query):
    with _inbox(FakeIMAP({})) as connect, pytest.raises(InvalidMailQuery):
        GmailInbox().list_messages("someone@gmail.com", "secret", query=query, limit=5)
    connect.assert_not_called()


def test_list_caps_the_limit():
    fake = FakeIMAP({uid: _raw(f"m{uid}") for uid in range(1, 81)})
    with _inbox(fake):
        messages = GmailInbox().list_messages("someone@gmail.com", "secret", query=None, limit=500)
    assert_that(len(messages), equal_to(50))


def test_list_of_an_empty_inbox_fetches_nothing():
    fake = FakeIMAP({})
    with _inbox(fake):
        assert_that(GmailInbox().list_messages("someone@gmail.com", "secret", query=None, limit=5), equal_to([]))
    assert_that(_fetches(fake), equal_to([]))


def test_searching_an_empty_inbox_sends_nothing():
    fake = FakeIMAP({})
    with _inbox(fake):
        assert_that(GmailInbox().list_messages("someone@gmail.com", "secret", query="x", limit=5), equal_to([]))
    assert_that([c for c in fake.commands if c[0] in {"fetch", "uid"}], equal_to([]))


def test_get_returns_text_and_attachment_names_without_marking_it_read():
    fake = FakeIMAP({7: _raw("invoice", attachment=True)})
    with _inbox(fake):
        message = GmailInbox().get_message("someone@gmail.com", "secret", "7")

    assert_that(message.id, equal_to("7"))
    assert_that(message.subject, equal_to("invoice"))
    assert_that(message.to, equal_to("someone@gmail.com"))
    assert_that(message.body, contains_string("Plain body for invoice"))
    assert_that(message.attachments, equal_to(["invoice.pdf"]))
    assert_that(message.truncated, is_(False))
    assert_that(_fetches(fake), equal_to(["(UID RFC822.SIZE)", "(UID BODY.PEEK[])"]))
    _assert_read_only(fake)


def test_get_of_a_huge_message_fetches_only_its_start():
    raw = _raw("big").replace(b"Plain body for big", b"y" * 3_000_000)
    fake = FakeIMAP({8: raw})
    with _inbox(fake):
        message = GmailInbox().get_message("someone@gmail.com", "secret", "8")

    assert_that(_fetches(fake), equal_to(["(UID RFC822.SIZE)", "(UID BODY.PEEK[]<0.2000000>)"]))
    assert_that(message.subject, equal_to("big"))
    assert_that(message.truncated, is_(True))
    _assert_read_only(fake)


def test_get_reads_a_part_in_an_unknown_charset_instead_of_failing():
    # Anyone can send the inbox a message that declares a charset Python does not know.
    raw = (
        b"From: x@example.com\r\nSubject: odd\r\nMIME-Version: 1.0\r\n"
        b'Content-Type: text/plain; charset="x-bogus"\r\n\r\nhello there'
    )
    fake = FakeIMAP({6: raw})
    with _inbox(fake):
        message = GmailInbox().get_message("someone@gmail.com", "secret", "6")

    assert_that(message.body, contains_string("hello there"))


def test_get_turns_an_html_only_message_into_text():
    message = EmailMessage()
    message["Subject"] = "html"
    message.set_content("<p>Hello <b>there</b></p><script>steal()</script><style>p{}</style>", subtype="html")
    fake = FakeIMAP({3: message.as_bytes()})
    with _inbox(fake):
        body = GmailInbox().get_message("someone@gmail.com", "secret", "3").body

    assert_that(body, equal_to("Hello there"))


def test_get_truncates_a_long_body():
    fake = FakeIMAP({4: _raw("long").replace(b"Plain body for long", b"x" * 60_000)})
    with _inbox(fake):
        message = GmailInbox().get_message("someone@gmail.com", "secret", "4")
    assert_that(len(message.body), equal_to(50_000))
    assert_that(message.truncated, is_(True))


def test_get_of_a_missing_message_is_not_found():
    fake = FakeIMAP({1: _raw("only")})
    with _inbox(fake), pytest.raises(MailNotFound):
        GmailInbox().get_message("someone@gmail.com", "secret", "99")
    _assert_read_only(fake)


@pytest.mark.parametrize("message_id", ["", "1,2", "1:*", "../1", "1 2", "-1", "\u0661\u0662", "1" * 21])
def test_get_refuses_anything_but_a_single_message_id_before_connecting(message_id):
    with _inbox(FakeIMAP({})) as connect, pytest.raises(MailNotFound):
        GmailInbox().get_message("someone@gmail.com", "secret", message_id)
    connect.assert_not_called()


def test_a_rejected_app_password_is_a_sign_in_failure():
    fake = FakeIMAP({}, login_error=True)
    with _inbox(fake), pytest.raises(MailSignInFailed):
        GmailInbox().list_messages("someone@gmail.com", "wrong", query=None, limit=5)
    assert_that(fake.commands[-1], equal_to(("logout",)))


def test_unreachable_gmail_is_unavailable():
    with patch.object(gmail_imap.imaplib, "IMAP4_SSL", side_effect=TimeoutError()), pytest.raises(MailUnavailable):
        GmailInbox().list_messages("someone@gmail.com", "secret", query=None, limit=5)


def test_check_sign_in_signs_in_and_out():
    fake = FakeIMAP({})
    with _inbox(fake):
        gmail_imap.check_sign_in("someone@gmail.com", "secret")
    assert_that(fake.commands, equal_to([("login", "someone@gmail.com", "secret"), ("logout",)]))


def test_check_sign_in_reports_a_rejected_password():
    with _inbox(FakeIMAP({}, login_error=True)), pytest.raises(MailSignInFailed):
        gmail_imap.check_sign_in("someone@gmail.com", "wrong")


class FlakyIMAP(FakeIMAP):
    """Gmail answering NO, dropping the connection, or failing to log out."""

    def __init__(
        self,
        messages,
        *,
        select_status="OK",
        search_status="OK",
        fetch_status="OK",
        drop_on=None,
        login_drop=False,
        logout_error=False,
    ):
        super().__init__(messages)
        self.select_status, self.search_status, self.fetch_status = select_status, search_status, fetch_status
        self.drop_on, self.login_drop, self.logout_error = drop_on, login_drop, logout_error

    def login(self, user, password):
        if self.login_drop:
            raise ConnectionResetError()
        return super().login(user, password)

    def select(self, mailbox="INBOX", readonly=False):
        super().select(mailbox, readonly)
        if self.drop_on == "SELECT":
            raise ConnectionResetError()
        return self.select_status, [str(self.exists).encode()]

    def fetch(self, message_set, query):
        if self.drop_on == "FETCH":
            raise ConnectionResetError()
        _, data = super().fetch(message_set, query)
        return self.fetch_status, data

    def uid(self, command, *args):
        if command == self.drop_on:
            raise ConnectionResetError()
        _, data = super().uid(command, *args)
        return (self.search_status if command == "SEARCH" else self.fetch_status), data

    def logout(self):
        super().logout()
        if self.logout_error:
            raise OSError("already closed")
        return "BYE", []


@pytest.mark.parametrize(
    "fake",
    [
        FlakyIMAP({1: _raw("a")}, select_status="NO"),
        FlakyIMAP({1: _raw("a")}, fetch_status="NO"),
        FlakyIMAP({1: _raw("a")}, drop_on="FETCH"),
        FlakyIMAP({1: _raw("a")}, login_drop=True),
        FlakyIMAP({1: _raw("a")}, drop_on="SELECT"),
    ],
    ids=[
        "select-refused",
        "fetch-refused",
        "dropped-mid-read",
        "dropped-at-login",
        "dropped-at-select",
    ],
)
def test_gmail_misbehaving_while_listing_is_unavailable(fake):
    with _inbox(fake), pytest.raises(MailUnavailable):
        GmailInbox().list_messages("someone@gmail.com", "secret", query=None, limit=5)
    assert_that(fake.commands[-1], equal_to(("logout",)))


@pytest.mark.parametrize(
    "fake",
    [
        FlakyIMAP({1: _raw("a")}, search_status="NO"),
        FlakyIMAP({1: _raw("a")}, drop_on="SEARCH"),
        FlakyIMAP({1: _raw("a")}, fetch_status="NO"),
    ],
    ids=["search-refused", "dropped-mid-search", "fetch-refused"],
)
def test_gmail_misbehaving_while_searching_is_unavailable(fake):
    with _inbox(fake), pytest.raises(MailUnavailable):
        GmailInbox().list_messages("someone@gmail.com", "secret", query="from:alice", limit=5)
    assert_that(fake.commands[-1], equal_to(("logout",)))


@pytest.mark.parametrize(
    "fake", [FlakyIMAP({1: _raw("a")}, fetch_status="NO"), FlakyIMAP({1: _raw("a")}, drop_on="FETCH")]
)
def test_gmail_misbehaving_while_reading_is_unavailable(fake):
    with _inbox(fake), pytest.raises(MailUnavailable):
        GmailInbox().get_message("someone@gmail.com", "secret", "1")


class UncountedIMAP(FakeIMAP):
    def select(self, mailbox="INBOX", readonly=False):
        super().select(mailbox, readonly)
        return "OK", [None]


class SizelessIMAP(FakeIMAP):
    def uid(self, command, *args):
        self.commands.append(("uid", command, *args))
        return "OK", [b"1 (UID 1 FLAGS ())"]


class NoMatchIMAP(FakeIMAP):
    def uid(self, command, *args):
        if command == "SEARCH":
            super().uid(command, *args)
            return "OK", [b""]
        return super().uid(command, *args)


class BodyFetchIMAP(FakeIMAP):
    """Reports the size, then refuses or loses the message when its body is fetched."""

    def __init__(self, messages, *, status: str):
        super().__init__(messages)
        self.status = status

    def uid(self, command, *args):
        status, data = super().uid(command, *args)
        if command == "FETCH" and "BODY.PEEK" in args[-1]:
            return self.status, []
        return status, data


def test_a_search_with_no_matches_fetches_nothing():
    fake = NoMatchIMAP({1: _raw("a")})
    with _inbox(fake):
        assert_that(GmailInbox().list_messages("someone@gmail.com", "secret", query="x", limit=5), equal_to([]))
    assert_that(_fetches(fake), equal_to([]))


def test_a_refused_body_fetch_is_unavailable():
    with _inbox(BodyFetchIMAP({1: _raw("a")}, status="NO")), pytest.raises(MailUnavailable):
        GmailInbox().get_message("someone@gmail.com", "secret", "1")


def test_a_message_gone_before_its_body_is_fetched_is_not_found():
    with _inbox(BodyFetchIMAP({1: _raw("a")}, status="OK")), pytest.raises(MailNotFound):
        GmailInbox().get_message("someone@gmail.com", "secret", "1")


def test_an_inbox_without_a_message_count_is_unavailable():
    with _inbox(UncountedIMAP({1: _raw("a")})), pytest.raises(MailUnavailable):
        GmailInbox().list_messages("someone@gmail.com", "secret", query=None, limit=5)


def test_a_message_without_a_reported_size_is_not_found():
    with _inbox(SizelessIMAP({1: _raw("a")})), pytest.raises(MailNotFound):
        GmailInbox().get_message("someone@gmail.com", "secret", "1")


def test_a_failed_logout_does_not_hide_the_result():
    fake = FlakyIMAP({1: _raw("a")}, logout_error=True)
    with _inbox(fake):
        assert_that(len(GmailInbox().list_messages("someone@gmail.com", "secret", query=None, limit=5)), equal_to(1))


def test_a_message_without_a_text_body_reads_as_empty():
    message = EmailMessage()
    message["Subject"] = "scan"
    message.add_attachment(b"%PDF", maintype="application", subtype="pdf", filename="scan.pdf")
    fake = FakeIMAP({5: message.as_bytes()})
    with _inbox(fake):
        read = GmailInbox().get_message("someone@gmail.com", "secret", "5")
    assert_that(read.body, equal_to(""))
    assert_that(read.attachments, equal_to(["scan.pdf"]))


class ImpostorIMAPServer:
    """A TLS server on localhost posing as Gmail with a self-signed certificate.

    It answers like an IMAP server would and records every line a client sends, so a
    test can see whether credentials were sent to it.
    """

    def __init__(self, cert_dir: Path):
        key = ec.generate_private_key(ec.SECP256R1())
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "not-gmail.invalid")])
        now = datetime.now(UTC)
        cert = (
            x509.CertificateBuilder()
            .subject_name(name)
            .issuer_name(name)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(days=1))
            .not_valid_after(now + timedelta(days=1))
            .add_extension(x509.SubjectAlternativeName([x509.DNSName("not-gmail.invalid")]), critical=False)
            .sign(key, hashes.SHA256())
        )
        cert_file, key_file = cert_dir / "cert.pem", cert_dir / "key.pem"
        cert_file.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        key_file.write_bytes(
            key.private_bytes(
                serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
            )
        )
        self._context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        self._context.load_cert_chain(cert_file, key_file)
        self._listener = socket.create_server(("127.0.0.1", 0))
        self._listener.settimeout(10)
        self.port = self._listener.getsockname()[1]
        self.received: list[bytes] = []
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self) -> None:
        try:
            raw, _ = self._listener.accept()
        except OSError:
            return
        try:
            with self._context.wrap_socket(raw, server_side=True) as conn:
                conn.settimeout(10)
                conn.sendall(b"* OK ready\r\n")
                reader = conn.makefile("rb")
                for line in reader:
                    self.received.append(line)
                    tag = line.split(b" ", 1)[0]
                    if b" CAPABILITY" in line.upper():
                        conn.sendall(b"* CAPABILITY IMAP4rev1 AUTH=PLAIN\r\n" + tag + b" OK done\r\n")
                        continue
                    if b" LOGOUT" in line.upper():
                        conn.sendall(b"* BYE\r\n" + tag + b" OK done\r\n")
                        return
                    conn.sendall(tag + b" NO [AUTHENTICATIONFAILED] no\r\n")
        except OSError:
            return

    def close(self) -> None:
        self._listener.close()
        self._thread.join(timeout=10)


@pytest.fixture
def impostor_gmail(tmp_path):
    server = ImpostorIMAPServer(tmp_path)
    with (
        patch.object(gmail_imap, "GMAIL_IMAP_HOST", "127.0.0.1"),
        patch.object(gmail_imap, "GMAIL_IMAP_PORT", server.port),
    ):
        yield server
    server.close()


def test_a_server_without_a_trusted_certificate_is_refused_before_signing_in(impostor_gmail):
    with pytest.raises(MailUnavailable):
        gmail_imap.check_sign_in("someone@gmail.com", "app-password-1234")
    impostor_gmail.close()
    assert_that(impostor_gmail.received, is_(empty()))


def test_reading_mail_from_a_server_without_a_trusted_certificate_sends_no_password(impostor_gmail):
    with pytest.raises(MailUnavailable):
        GmailInbox().list_messages("someone@gmail.com", "app-password-1234", query=None, limit=5)
    impostor_gmail.close()
    assert_that(impostor_gmail.received, is_(empty()))
