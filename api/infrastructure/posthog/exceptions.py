class PostHogException(Exception):
    pass


class RetryablePostHogException(PostHogException):
    pass


class TerminalPostHogException(PostHogException):
    pass
