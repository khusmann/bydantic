from __future__ import annotations
import typing as t


def _make_pairs(order: t.Sequence[int], size: int):
    if not all(i < size for i in order) or not all(i >= 0 for i in order):
        raise ValueError(
            f"some indices in the reordering are out-of-bounds"
        )

    order_set = frozenset(order)

    if len(order_set) != len(order):
        raise ValueError(
            f"duplicate indices in reordering"
        )

    return zip(
        range(size),
        (*order, *(i for i in range(size) if i not in order_set))
    )


def reorder_bits(data: t.Sequence[bool], order: t.Sequence[int]) -> t.Tuple[bool, ...]:
    if not order:
        return tuple(data)

    pairs = _make_pairs(order, len(data))

    return tuple(data[i] for _, i in pairs)


def unreorder_bits(data: t.Sequence[bool], order: t.Sequence[int]) -> t.Tuple[bool, ...]:
    if not order:
        return tuple(data)

    pairs = sorted(_make_pairs(order, len(data)), key=lambda x: x[1])

    return tuple(data[i] for i, _ in pairs)


def bytes_to_bits(data: t.ByteString) -> t.Tuple[bool, ...]:
    return tuple(
        bit for byte in data for bit in int_to_bits(byte, 8)
    )


def int_to_bits(x: int, n: int) -> t.Tuple[bool, ...]:
    if x < 0:
        raise ValueError("int must be non-negative")

    if x.bit_length() > n:
        raise ValueError(f"int too large for {n} bits")

    return tuple(x & (1 << (n - i - 1)) != 0 for i in range(n))


def bits_to_int(bits: t.Sequence[bool]) -> int:
    return sum((bit << (len(bits) - i - 1) for i, bit in enumerate(bits)))


def bits_to_bytes(bits: t.Sequence[bool]) -> bytes:
    if len(bits) % 8:
        raise ValueError("bits must be byte aligned (multiple of 8 bits)")

    return bytes(
        bits_to_int(bits[i:i+8]) for i in range(0, len(bits), 8)
    )


class BitstreamWriter:
    _bits: t.Tuple[bool, ...]

    def __init__(self, bits: t.Sequence[bool] = ()) -> None:
        self._bits = tuple(bits)

    def put(self, bits: t.Sequence[bool]):
        return BitstreamWriter(self._bits + tuple(bits))

    def put_int(self, x: int, n: int):
        return self.put(int_to_bits(x, n))

    def put_bytes(self, data: t.ByteString):
        return self.put(bytes_to_bits(data))

    def __repr__(self) -> str:
        str_bits = "".join(str(int(bit)) for bit in self._bits)
        return f"{self.__class__.__name__}({str_bits})"

    def as_bits(self) -> t.Tuple[bool, ...]:
        return self._bits

    def as_bytes(self) -> bytes:
        return bits_to_bytes(self._bits)

    def unreorder(self, order: t.Sequence[int]) -> BitstreamWriter:
        return BitstreamWriter(unreorder_bits(self._bits, order))


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

    def take_int(self, n: int):
        value, stream = self.take(n)
        return bits_to_int(value), stream

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

    def reorder(self, order: t.Sequence[int]) -> BitstreamReader:
        return BitstreamReader(reorder_bits(self._bits, order))


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


class NotProvided:
    def __repr__(self): return "<NotProvided>"


NOT_PROVIDED = NotProvided()


_T = t.TypeVar("_T")


def is_provided(x: _T | NotProvided) -> t.TypeGuard[_T]:
    return x is not NOT_PROVIDED
