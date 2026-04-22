from datetime import datetime, timezone, tzinfo


class Clock:
    clock_instance = None

    def get_now(self) -> datetime:
        return datetime.now(timezone.utc)

    def now(self) -> datetime:
        return datetime.now(timezone.utc)

    def get_local_now(self, timezone: tzinfo) -> datetime:
        return self.get_now().astimezone(timezone)

    @classmethod
    def set_clock(cls, clock):
        cls.clock_instance = clock

    @classmethod
    def retrieve(cls):
        if cls.clock_instance is None:
            cls.clock_instance = Clock()

        return cls.clock_instance
