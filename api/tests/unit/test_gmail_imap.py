"""Read-only Gmail over IMAP: what the gateway sends to Gmail on an agent's behalf.

A fake IMAP connection records every command, so these tests prove the reader only
ever opens the inbox read-only and only fetches with BODY.PEEK.
"""

import imaplib
from email.message import EmailMessage
from unittest.mock import patch

import pytest
from hamcrest import assert_that, contains_string, equal_to, is_

from api.infrastructure.google import gmail_imap
from api.infrastructure.google.gmail_imap import (
    GmailInbox,
    InvalidMailQuery,
    MailNotFound,
    MailSignInFailed,
    MailUnavailable,
)

_READ_ONLY_COMMANDS = {"login", "select", "uid", "logout"}


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
    """Answers like imaplib.IMAP4_SSL for a small inbox and records each command."""

    def __init__(self, messages: dict[int, bytes], *, login_error: bool = False):
        self.messages = messages
        self.login_error = login_error
        self.commands: list[tuple] = []

    def login(self, user, password):
        self.commands.append(("login", user, password))
        if self.login_error:
            raise imaplib.IMAP4.error("[AUTHENTICATIONFAILED] Invalid credentials")
        return "OK", [b"Logged in"]

    def select(self, mailbox="INBOX", readonly=False):
        self.commands.append(("select", mailbox, readonly))
        return "OK", [str(len(self.messages)).encode()]

    def uid(self, command, *args):
        self.commands.append(("uid", command, *args))
        if command == "SEARCH":
            return "OK", [b" ".join(str(uid).encode() for uid in sorted(self.messages))]
        if command == "FETCH":
            uid_set, query = args
            parts: list = []
            for uid in [int(u) for u in uid_set.split(",")]:
                if uid not in self.messages:
                    continue
                raw = self.messages[uid]
                body = raw.split(b"\n\n", 1)[0] if "HEADER.FIELDS" in query else raw
                parts.append((f"{uid} (UID {uid} BODY[] {{{len(body)}}}".encode(), body))
                parts.append(b")")
            return "OK", parts
        raise AssertionError(f"unexpected UID command {command}")

    def logout(self):
        self.commands.append(("logout",))
        return "BYE", []

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        raise AssertionError(f"the reader must not call IMAP {name}")


def _inbox(fake: FakeIMAP):
    return patch.object(gmail_imap.imaplib, "IMAP4_SSL", return_value=fake)


def _assert_read_only(fake: FakeIMAP):
    assert_that({c[0] for c in fake.commands} <= _READ_ONLY_COMMANDS, is_(True))
    assert_that([c for c in fake.commands if c[0] == "select"], equal_to([("select", "INBOX", True)]))
    for command in fake.commands:
        if command[:2] == ("uid", "FETCH"):
            assert_that(command[3], contains_string("BODY.PEEK"))
    assert_that(fake.commands[-1], equal_to(("logout",)))


def test_list_returns_newest_first_and_never_changes_the_mailbox():
    fake = FakeIMAP({1: _raw("first"), 2: _raw("second"), 3: _raw("third")})
    with _inbox(fake) as connect:
        messages = GmailInbox().list_messages("someone@gmail.com", "secret", query=None, limit=2)

    connect.assert_called_once_with("imap.gmail.com", timeout=20)
    assert_that([m.id for m in messages], equal_to(["3", "2"]))
    assert_that(messages[0].subject, equal_to("third"))
    assert_that(messages[0].sender, equal_to("Alice <alice@example.com>"))
    assert_that(fake.commands[0], equal_to(("login", "someone@gmail.com", "secret")))
    assert_that(("uid", "SEARCH", "ALL") in fake.commands, is_(True))
    _assert_read_only(fake)


def test_list_passes_a_gmail_search_as_one_quoted_argument():
    fake = FakeIMAP({1: _raw("hello")})
    with _inbox(fake):
        GmailInbox().list_messages("someone@gmail.com", "secret", query='from:alice "a\\b"', limit=5)

    assert_that(("uid", "SEARCH", "X-GM-RAW", '"from:alice \\"a\\\\b\\""') in fake.commands, is_(True))
    _assert_read_only(fake)


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
    assert_that([c for c in fake.commands if c[:2] == ("uid", "FETCH")], equal_to([]))


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
    assert_that(("uid", "FETCH", "7", "(BODY.PEEK[])") in fake.commands, is_(True))
    _assert_read_only(fake)


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


@pytest.mark.parametrize("message_id", ["", "1,2", "1:*", "../1", "1 2", "-1"])
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
        return self.select_status, [b""]

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
        FlakyIMAP({1: _raw("a")}, search_status="NO"),
        FlakyIMAP({1: _raw("a")}, fetch_status="NO"),
        FlakyIMAP({1: _raw("a")}, drop_on="SEARCH"),
        FlakyIMAP({1: _raw("a")}, login_drop=True),
        FlakyIMAP({1: _raw("a")}, drop_on="SELECT"),
    ],
    ids=[
        "select-refused",
        "search-refused",
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
    "fake", [FlakyIMAP({1: _raw("a")}, fetch_status="NO"), FlakyIMAP({1: _raw("a")}, drop_on="FETCH")]
)
def test_gmail_misbehaving_while_reading_is_unavailable(fake):
    with _inbox(fake), pytest.raises(MailUnavailable):
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
