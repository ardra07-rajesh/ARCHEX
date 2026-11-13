from .alu import to_signed


class RegisterFile:
    """R0 is hard-wired to zero; writes to it are ignored."""

    def __init__(self, count: int):
        self.count = count
        self.values = [0] * count

    def read(self, i: int) -> int:
        return self.values[i]

    def write(self, i: int, v: int) -> None:
        if i != 0:
            self.values[i] = to_signed(v)

    def snapshot(self) -> list[int]:
        return list(self.values)
