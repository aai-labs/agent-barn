class EmailException(Exception):
    email: str
    message: str

    def __init__(self, message: str, email: str):
        super().__init__(message)
        self.email = email
        self.message = message


class EmailSendingException(EmailException):
    pass


class EmailRenderingException(EmailException):
    pass
