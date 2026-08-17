class EmailException(Exception):
    email: str
    message: str

    def __init__(self, message: str, email: str):
        super().__init__(message)
        self.email = email
        self.message = message


class EmailSendingException(EmailException):
    pass


class RetryableEmailSendingException(EmailSendingException):
    """The send may succeed if attempted again — rate limiting, a 5xx, or a transport
    failure. Event handlers should let the delivery framework retry."""


class TerminalEmailSendingException(EmailSendingException):
    """The send will never succeed as submitted — a rejected payload, bad credentials,
    an unverified sending domain, or a permanent bounce. Retrying only burns the budget."""


class EmailRenderingException(EmailException):
    pass
