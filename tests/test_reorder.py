import bydantic as bd
import typing as t
from bydantic.utils import (
    reorder_bits,
    unreorder_bits
)


def test_bit_reorder():
    b = tuple(i == "1" for i in "101100")
    order = [1, 3, 5]

    assert reorder_bits(b, order) == tuple(i == "1" for i in "010110")
    assert unreorder_bits(reorder_bits(b, order), order) == b


def test_basic_reorder():
    class Work(bd.Bitfield):
        a: int = bd.uint_field(4)
        b: t.List[int] = bd.list_field(bd.uint_field(3), 4)
        c: str = bd.str_field(n_bytes=3)
        d: bytes = bd.bytes_field(n_bytes=4)

        bitfield_config = bd.BitfieldConfig(
            reorder_bits=[*range(56, 56+16)]
        )

    work = Work(a=1, b=[1, 2, 3, 4], c="abc", d=b"abcd")
    assert work.to_bytes() == b'abcabcd\x12\x9c'
    assert Work.from_bytes_exact(work.to_bytes()) == work
