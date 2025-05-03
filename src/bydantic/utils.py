from __future__ import annotations
import typing as t


def bytes_to_bits(data: t.ByteString) -> t.Tuple[bool, ...]:
    return tuple(
        bit for byte in data for bit in uint_to_bits(byte, 8)
    )


def uint_to_bits(x: int, n: int) -> t.Tuple[bool, ...]:
    if x < 0:
        raise ValueError("value must be non-negative")

    if is_int_too_big(x, n, signed=False):
        raise ValueError(f"value ({x}) does not fit in {n} bits")

    return tuple(x & (1 << (n - i - 1)) != 0 for i in range(n))


def is_int_too_big(x: int, n: int, signed: bool) -> bool:
    if signed:
        return not -(1 << (n-1)) <= x < (1 << (n-1))
    else:
        return not 0 <= x < (1 << n)


def bits_to_uint(bits: t.Sequence[bool]) -> int:
    return sum((bit << (len(bits) - i - 1) for i, bit in enumerate(bits)))


def bits_to_bytes(bits: t.Sequence[bool]) -> bytes:
    if len(bits) % 8:
        raise ValueError("bits must be byte aligned (multiple of 8 bits)")

    return bytes(
        bits_to_uint(bits[i:i+8]) for i in range(0, len(bits), 8)
    )


class BitstreamWriter:
    _bits: t.Tuple[bool, ...]

    def __init__(self, bits: t.Sequence[bool] = ()) -> None:
        self._bits = tuple(bits)

    def put(self, bits: t.Sequence[bool]):
        return BitstreamWriter(self._bits + tuple(bits))

    def put_uint(self, x: int, n: int):
        return self.put(uint_to_bits(x, n))

    def put_bytes(self, data: t.ByteString):
        return self.put(bytes_to_bits(data))

    def __repr__(self) -> str:
        str_bits = "".join(str(int(bit)) for bit in self._bits)
        return f"{self.__class__.__name__}({str_bits})"

    def as_bits(self) -> t.Tuple[bool, ...]:
        return self._bits

    def as_bytes(self) -> bytes:
        return bits_to_bytes(self._bits)


class BitstreamReader:
    _bits: t.Tuple[bool, ...]
    _pos: int

    def __init__(self, bits: t.Sequence[bool] = (), pos: int = 0) -> None:
        self._bits = tuple(bits)
        self._pos = pos

    @classmethod
    def from_bits(cls, bits: t.Sequence[bool]) -> BitstreamReader:
        return cls(bits)

    @classmethod
    def from_bytes(cls, data: t.ByteString) -> BitstreamReader:
        return cls(bytes_to_bits(data))

    def bits_remaining(self):
        return len(self._bits) - self._pos

    def bytes_remaining(self):
        if self.bits_remaining() % 8:
            raise ValueError(
                "BitStream is not byte aligned (multiple of 8 bits)")

        return self.bits_remaining() // 8

    def take(self, n: int):
        if n > self.bits_remaining():
            raise EOFError("Unexpected end of bitstream")

        return self._bits[self._pos:n+self._pos], BitstreamReader(self._bits, self._pos+n)

    def take_uint(self, n: int):
        value, stream = self.take(n)
        return bits_to_uint(value), stream

    def take_bytes(self, n_bytes: int):
        value, stream = self.take(n_bytes*8)
        return bits_to_bytes(value), stream

    def take_stream(self, n: int):
        bits, stream = self.take(n)
        return BitstreamReader(bits), stream

    def __repr__(self) -> str:
        str_bits = "".join(str(int(bit)) for bit in self._bits[self._pos:])
        return f"{self.__class__.__name__}({str_bits})"

    def as_bits(self) -> t.Tuple[bool, ...]:
        return self.take(self.bits_remaining())[0]

    def as_bytes(self) -> bytes:
        return self.take_bytes(self.bytes_remaining())[0]


class AttrProxy(t.Mapping[str, t.Any]):
    _data: t.Dict[str, t.Any]

    def __init__(self, data: t.Mapping[str, t.Any] = {}) -> None:
        self._data = dict(data)

    def __getitem__(self, key: str):
        return self._data[key]

    def __setitem__(self, key: str, value: t.Any):
        self._data[key] = value

    def __iter__(self):
        return iter(self._data)

    def __len__(self):
        return len(self._data)

    def __getattr__(self, key: str):
        if key in self._data:
            return self._data[key]
        raise AttributeError(
            f"'AttrProxy' object has no attribute '{key}'"
        )

    def __repr__(self):
        return f"AttrProxy({self._data})"


_T = t.TypeVar("_T")


class NotProvided:
    def __repr__(self): return "<NotProvided>"


NOT_PROVIDED = NotProvided()


def is_provided(x: _T | NotProvided) -> t.TypeGuard[_T]:
    return x is not NOT_PROVIDED


def ellipsis_to_not_provided(x: _T | ellipsis) -> _T | NotProvided:
    return NOT_PROVIDED if x is ... else x
