from typing import Any


class GivenScope:
    def __init__(self, steps):
        self.steps = steps or []

        class Context:
            pass

        self.context: Any = Context()
        self.started_steps = []

    def __enter__(self):
        context = self.context
        if self.steps:
            for step in self.steps:
                result = step(context)
                self.started_steps += [result]
                if result and hasattr(result, "__enter__"):
                    result.__enter__()
        return context

    def __exit__(self, exc_type, value, traceback):
        for step in reversed(self.started_steps):
            if step and hasattr(step, "__exit__"):
                step.__exit__(exc_type, value, traceback)


def given(steps=None):
    return GivenScope(steps)


def when(description=None):
    return MockWith()


def then(message=None):
    return MockWith()


def but(message=None):
    return MockWith()


class MockWith:
    def __enter__(self):
        pass

    def __exit__(self, exc_type, value, traceback):
        pass

    def __getattribute__(self, item):
        return MockWith()


class LambdaWith:
    def __init__(self, enter, leave):
        self.enter = enter
        self.leave = leave

    def __enter__(self):
        self.enter()

    def __exit__(self, exc_type, value, traceback):
        self.leave()


def resulting(param=None):
    return MockWith()
