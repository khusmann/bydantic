from __future__ import annotations

import typing as t
import pytest
import re

from enum import IntEnum

import bydantic as bd


def test_basic():
    class Work(bd.Bitfield):
        a: int = bd.uint_field(4)
        b: t.List[int] = bd.list_field(bd.uint_field(3), 4)
        c: str = bd.str_field(n_bytes=3)
        d: bytes = bd.bytes_field(n_bytes=4)

    work = Work(a=1, b=[1, 2, 3, 4], c="abc", d=b"abcd")
    assert work.to_bytes() == b'\x12\x9cabcabcd'
    assert Work.from_bytes_exact(work.to_bytes()) == work


def test_bitfield_field():
    class Inner(bd.Bitfield):
        a: int = bd.uint_field(4)
        b: str = bd.str_field(n_bytes=3)

    class Work(bd.Bitfield):
        a: int = bd.uint_field(4)
        b: Inner = bd.bitfield_field(Inner, 28)

    work = Work(a=1, b=Inner(a=2, b="abc"))
    assert work.to_bytes() == b'\x12abc'
    assert Work.from_bytes_exact(work.to_bytes()) == work

    class Work2(bd.Bitfield):
        a: int = bd.uint_field(4)
        b: Inner = bd.bitfield_field(Inner)

    work2 = Work2(a=1, b=Inner(a=2, b="abc"))
    assert work2.to_bytes() == b'\x12abc'
    assert Work2.from_bytes_exact(work2.to_bytes()) == work2

    class Work3(bd.Bitfield):
        a: int = bd.uint_field(4)
        b: Inner

    work3 = Work3(a=1, b=Inner(a=2, b="abc"))
    assert work3.to_bytes() == b'\x12abc'
    assert Work3.from_bytes_exact(work3.to_bytes()) == work3

    with pytest.raises(TypeError):
        class InnerDyn(bd.Bitfield):
            a: int | None = bd.dynamic_field(
                lambda x: bd.uint_field(4) if x.a == 0 else None
            )

        class Fail(bd.Bitfield):
            a: int = bd.uint_field(4)
            b: InnerDyn
        print(Fail)


def test_none():
    class Work(bd.Bitfield):
        a: int = bd.uint_field(8)
        b: None = None

    work = Work(a=1)
    assert work.to_bytes() == b'\x01'
    assert Work.from_bytes_exact(work.to_bytes()) == work


def test_str_field():
    class Work(bd.Bitfield):
        a: str = bd.str_field(n_bytes=8)

    work = Work(a="hello")
    assert work.to_bytes() == b'hello\x00\x00\x00'
    assert Work.from_bytes_exact(work.to_bytes()) == work

    work2 = Work(a="你好")
    assert work2.to_bytes() == b'\xe4\xbd\xa0\xe5\xa5\xbd\x00\x00'
    assert Work.from_bytes_exact(work2.to_bytes()) == work2

    with pytest.raises(bd.SerializeFieldError):
        Work(a="123456789").to_bytes()


def test_basic_context():
    class Opts(t.NamedTuple):
        a: int

    def ctx_disc(x: Foo):
        if x.ctx is None:
            return None

        if x.ctx.a == 10:
            return bd.uint_field(8)
        else:
            return None

    class Foo(bd.Bitfield[Opts]):
        z: int | None = bd.dynamic_field(ctx_disc)

    foo = Foo(z=None)
    assert foo.to_bytes() == b''
    assert Foo.from_bytes_exact(foo.to_bytes()) == foo

    foo = Foo(z=5)
    assert foo.to_bytes(Opts(a=10)) == b'\x05'
    foo2 = Foo.from_bytes_exact(b'\x05', Opts(a=10))
    assert foo2 == foo

    assert foo.ctx == None
    assert foo2.ctx == None


def test_basic_subclasses():
    class Work(bd.Bitfield):
        a: int = bd.uint_field(4)
        b: t.List[int] = bd.list_field(bd.uint_field(3), 4)

    class Work2(Work):
        c: str = bd.str_field(n_bytes=3)
        d: bytes = bd.bytes_field(n_bytes=4)

    work = Work(a=1, b=[1, 2, 3, 4])
    assert work.to_bytes() == b'\x12\x9c'
    assert Work.from_bytes_exact(work.to_bytes()) == work

    work2 = Work2(a=1, b=[1, 2, 3, 4], c="abc", d=b"abcd")
    assert work2.to_bytes() == b'\x12\x9cabcabcd'
    assert Work2.from_bytes_exact(work2.to_bytes()) == work2


def test_classvars():
    class Work(bd.Bitfield):
        a: int = bd.uint_field(4)
        b: int = bd.uint_field(4)
        c = 100
        d: t.ClassVar[int] = 100

    work = Work(a=1, b=2)
    assert work.to_bytes() == b'\x12'
    assert Work.from_bytes_exact(work.to_bytes()) == work


def test_kitchen_sink():
    class BarEnum(IntEnum):
        A = 1
        B = 2
        C = 3

    class Baz(bd.Bitfield):
        a: int = bd.uint_field(3)
        b: int = bd.uint_field(10)

    def foo(x: Foo) -> t.Literal[10] | list[float]:
        if x.ab == 1:
            return bd.list_field(bd.mapped_field(bd.uint_field(5), bd.Scale(100)), 1)
        else:
            return bd.lit_uint_field(5, default=10)

    class Foo(bd.Bitfield):
        a: float = bd.mapped_field(bd.uint_field(2), bd.Scale(1 / 2))
        _pad: t.Literal[0x5] = bd.lit_uint_field(3, default=0x5)
        ff: Baz
        ay: t.Literal[b'world'] = b'world'
        ab: int = bd.uint_field(10)
        ac: int = bd.uint_field(2)
        zz: BarEnum = bd.uint_enum_field(BarEnum, 2)
        yy: bytes = bd.bytes_field(n_bytes=2)
        ad: int = bd.uint_field(3)
        c: t.Literal[10] | list[float] | Baz = bd.dynamic_field(foo)
        d: t.List[int] = bd.list_field(bd.uint_field(10), 3)
        e: t.List[Baz] = bd.list_field(Baz, 3)
        f: t.Literal["Hello"] = bd.lit_str_field(default="Hello")
        h: t.Literal[b"Hello"] = b"Hello"
        g: t.List[t.List[int]] = bd.list_field(
            bd.list_field(bd.uint_field(10), 3), 3)
        xx: bool

    f = Foo(
        a=0.5,
        ff=Baz(a=1, b=2),
        ab=0x3ff,
        ac=3,
        zz=BarEnum.B,
        yy=b'hi',
        ad=3,
        c=10,
        d=[1, 2, 3],
        e=[Baz(a=1, b=2), Baz(a=3, b=4), Baz(a=5, b=6)],
        g=[[1, 2, 3], [4, 5, 6], [7, 8, 9]],
        xx=True,
    )

    assert f.to_bytes() == b'i\x00\x9d\xdb\xdc\x9b\x19?\xfehij\x00@ \x0c\x80L\x04\xa02C+cczC+ccx\x02\x01\x00` \n\x03\x00\xe0@\x13'
    assert Foo.from_bytes_exact(f.to_bytes()) == f


def test_default_len_err():
    class Work(bd.Bitfield):
        a: str = bd.str_field(n_bytes=4, default="ทt")
        b: bytes = bd.bytes_field(n_bytes=3, default=b"abc")
        c: t.Literal["ทt"] = bd.lit_str_field(default="ทt")
        d: t.List[int] = bd.list_field(
            bd.uint_field(3), 4, default=[1, 2, 3, 4])

    assert Work.length() == 11*8 + 3*4

    with pytest.raises(ValueError, match=re.escape("expected default string of maximum length 3 bytes, got 4 bytes ('ทt')")):
        class Fail1(bd.Bitfield):
            a: str = bd.str_field(n_bytes=3, default="ทt")
        print(Fail1)

    with pytest.raises(ValueError, match=re.escape("expected default bytes of length 4 bytes, got 3 bytes (b'abc')")):
        class Fail2(bd.Bitfield):
            a: bytes = bd.bytes_field(n_bytes=4, default=b"abc")
        print(Fail2)

    with pytest.raises(ValueError, match=re.escape("expected default list of length 4, got 3 ([1, 2, 3])")):
        class Fail3(bd.Bitfield):
            a: t.List[int] = bd.list_field(
                bd.uint_field(3), 4, default=[1, 2, 3])
        print(Fail3)


def test_incorrect_field_types():
    with pytest.raises(TypeError, match=re.escape("in definition of 'Fail1.a': expected a field type, got 1")):
        class Fail1(bd.Bitfield):
            a: int = 1
        print(Fail1)

    with pytest.raises(TypeError, match=re.escape("in definition of 'Fail2.a': missing field definition")):
        class Fail2(bd.Bitfield):
            a: int
        print(Fail2)


def test_dyn_infer_err():
    class DynFoo(bd.Bitfield):
        a: int = bd.dynamic_field(lambda _, __: bd.uint_field(4))

    with pytest.raises(TypeError, match=re.escape("in definition of 'Fail.a': cannot infer length for dynamic Bitfield")):
        class Fail(bd.Bitfield):
            a: DynFoo
        print(Fail)


def test_lit_field_err():
    with pytest.raises(TypeError, match=re.escape("in definition of 'Fail.a': literal must have exactly one argument")):
        class Fail(bd.Bitfield):
            a: t.Literal[1, 2]
        print(Fail)


def test_default_children_err():
    with pytest.raises(ValueError, match=re.escape("in definition of 'Fail.a': inner field definitions cannot have defaults set (except literal fields)")):
        class Fail(bd.Bitfield):
            a: t.List[int] = bd.list_field(bd.uint_field(4, default=10), 4)
        print(Fail)


def test_nested_deserialize_error():
    class InnerFoo(bd.Bitfield):
        a: t.Literal[1] = bd.lit_uint_field(4, default=1)
        b: int = bd.uint_field(4)
        c: int = bd.uint_field(8)

    class Bar(bd.Bitfield):
        z: InnerFoo = bd.bitfield_field(InnerFoo, 8)

    with pytest.raises(bd.DeserializeFieldError, match=re.escape("ValueError in field 'Bar.z.a': expected literal 1, got 0")):
        Bar.from_bytes_exact(b'\x00')

    with pytest.raises(bd.DeserializeFieldError, match=re.escape("EOFError in field 'Bar.z.c': Unexpected end of bitstream")):
        Bar.from_bytes_exact(b'\x10')


def test_dyn_error():
    class Foo(bd.Bitfield):
        a: int = bd.uint_field(8)
        b: int | str = bd.dynamic_field(
            lambda x: bd.uint_field(8) if x.a == 0 else bd.str_field(n_bytes=1)
        )

    Foo(a=0, b=1).to_bits()
    Foo(a=1, b="a").to_bits()

    with pytest.raises(bd.SerializeFieldError, match=re.escape("TypeError in field 'Foo.b': expected str, got int")):
        Foo(a=1, b=1).to_bits()

    with pytest.raises(bd.SerializeFieldError, match=re.escape("TypeError in field 'Foo.b': expected int, got str")):
        Foo(a=0, b="a").to_bits()


def test_int_enum():
    class UnsignedEnum(IntEnum):
        A = 1
        B = 2
        C = 3

    class SignedEnum(IntEnum):
        A = -1
        B = 0
        C = 1

    class Foo(bd.Bitfield):
        a: UnsignedEnum = bd.uint_enum_field(UnsignedEnum, 4)
        b: SignedEnum = bd.int_enum_field(SignedEnum, 4)

    foo = Foo(a=UnsignedEnum.A, b=SignedEnum.A)
    assert foo.to_bytes() == b'\x1f'
    assert Foo.from_bytes_exact(foo.to_bytes()) == foo

    with pytest.raises(ValueError):
        class Fail1(bd.Bitfield):
            a: SignedEnum = bd.uint_enum_field(SignedEnum, 4)
        print(Fail1)


def test_signed_int():
    class Foo(bd.Bitfield):
        a: int = bd.int_field(8)

    assert Foo(a=-1).to_bytes() == b'\xff'
    assert Foo.from_bytes_exact(b'\xff') == Foo(a=-1)

    with pytest.raises(bd.SerializeFieldError):
        Foo(a=-129).to_bytes()
        Foo(a=128).to_bytes()

    with pytest.raises(ValueError):
        class Fail1(bd.Bitfield):
            a: int = bd.int_field(8, default=128)
        print(Fail1)

    with pytest.raises(ValueError):
        class Fail2(bd.Bitfield):
            a: int = bd.int_field(8, default=-129)
        print(Fail2)


def test_context():
    class Ctx(t.NamedTuple):
        a: bool

    def foo_disc(x: Foo):
        if not x.ctx:
            raise ValueError("context not set")

        if x.ctx.a:
            return bd.uint_field(8)
        else:
            return bd.str_field(n_bytes=1)

    class Foo(bd.Bitfield[Ctx]):
        a: int | str = bd.dynamic_field(foo_disc)

    assert Foo(a=1).to_bytes(Ctx(a=True)) == b'\x01'
    assert Foo(a="a").to_bytes(Ctx(a=False)) == b'a'

    assert Foo.from_bytes_exact(b'\x01', Ctx(a=True)) == Foo(a=1)
    assert Foo.from_bytes_exact(b'a', Ctx(a=False)) == Foo(a="a")
