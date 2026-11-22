import threading
import time
from unittest.mock import DEFAULT, MagicMock


class OverlapProbe:
    """Makes mocked reads slow and counts how many run at once.

    Each wrapped call holds for ``hold_seconds`` before answering as the mock otherwise
    would (its own ``side_effect``, or its ``return_value``), so reads made one after
    another peak at 1 and reads made together peak at how many overlap. Counting beats
    timing a request, which a busy CI machine makes unreliable.
    """

    def __init__(self, hold_seconds: float = 0.3):
        self.hold_seconds = hold_seconds
        self.peak = 0
        self._active = 0
        self._lock = threading.Lock()

    def slow(self, *mocks: MagicMock) -> None:
        for mock in mocks:
            original = mock.side_effect

            def call(*args, _original=original, **kwargs):
                with self._lock:
                    self._active += 1
                    self.peak = max(self.peak, self._active)
                try:
                    time.sleep(self.hold_seconds)
                    return _original(*args, **kwargs) if callable(_original) else DEFAULT
                finally:
                    with self._lock:
                        self._active -= 1

            mock.side_effect = call
