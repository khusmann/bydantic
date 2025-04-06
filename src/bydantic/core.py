from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from typing_extensions import dataclass_transform, TypeVar as TypeVarDefault, Self
import typing as t
import inspect
import numbers

from enum import IntEnum, IntFlag

from .utils import (
    BitstreamReader,
    BitstreamWriter,
    AttrProxy,
    NotProvided,
    is_provided,
    NOT_PROVIDED,
    ellipsis_to_not_provided,
    is_int_too_big,
)


class FieldError(Exception):
    inner: Exception
    class_name: str
    field_stack: t.Tuple[str, ...]

    def __init__(self, e: Exception, class_name: str, field_name: str):
        self.inner = e
        self.class_name = class_name
        self.field_stack = (field_name,)

    def push_stack(self, class_name: str, field_name: str):
        self.class_name = class_name
        self.field_stack = (field_name,) + self.field_stack

    def __str__(self) -> str:
        return f"{self.inner.__class__.__name__} in field '{self.class_name}.{'.'.join(self.field_stack)}': {str(self.inner)}"


class DeserializeFieldError(FieldError):
    pass


class SerializeFieldError(FieldError):
    pass


T = t.TypeVar("T")
P = t.TypeVar("P")


class ValueMapper(t.Protocol[T, P]):
    def forward(self, x: T) -> P: ...
    def back(self, y: P) -> T: ...


class Scale(t.NamedTuple):
    by: float
    n_digits: int | None = None

    def forward(self, x: int):
        value = x * self.by
        return value if self.n_digits is None else round(value, self.n_digits)

    def back(self, y: float):
        return round(y / self.by)


class IntScale(t.NamedTuple):
    by: int

    def forward(self, x: int):
        return x * self.by

    def back(self, y: int):
        return round(y / self.by)


class BFBits(t.NamedTuple):
    n: int
    default: t.Sequence[bool] | NotProvided


class BFUInt(t.NamedTuple):
    n: int
    default: int | NotProvided


class BFList(t.NamedTuple):
    inner: BFType
    n: int
    default: t.List[t.Any] | NotProvided


class BFMap(t.NamedTuple):
    inner: BFType
    vm: ValueMapper[t.Any, t.Any]
    default: t.Any | NotProvided


class BFDynSelf(t.NamedTuple):
    fn: t.Callable[[t.Any], Field[t.Any]]
    default: t.Any | NotProvided


class BFDynSelfN(t.NamedTuple):
    fn: t.Callable[[t.Any, int], Field[t.Any]]
    default: t.Any | NotProvided


class BFLit(t.NamedTuple):
    inner: BFType
    default: t.Any


class BFBitfield(t.NamedTuple):
    inner: t.Type[Bitfield]
    n: int
    default: Bitfield | NotProvided


class BFNone(t.NamedTuple):
    default: None | NotProvided


BFType = t.Union[
    BFBits,
    BFUInt,
    BFList,
    BFMap,
    BFDynSelf,
    BFDynSelfN,
    BFLit,
    BFNone,
    BFBitfield,
]


def bftype_length(bftype: BFType) -> int | None:
    match bftype:
        case BFBits(n=n) | BFBitfield(n=n) | BFUInt(n=n):
            return n

        case BFList(inner=inner, n=n):
            item_len = bftype_length(inner)
            return None if item_len is None else n * item_len

        case BFMap(inner=inner) | BFLit(inner=inner):
            return bftype_length(inner)

        case BFNone():
            return 0

        case BFDynSelf() | BFDynSelfN():
            return None


def bftype_has_children_with_default(bftype: BFType) -> bool:
    match bftype:
        case BFBits() | BFUInt() | BFBitfield() | BFNone() | BFDynSelf() | BFDynSelfN():
            return False

        case BFList(inner=inner) | BFMap(inner=inner) | BFLit(inner=inner):
            return is_provided(inner.default) or bftype_has_children_with_default(inner)


Field = t.Annotated[T, "BFTypeDisguised"]


def disguise(x: BFType) -> Field[t.Any]:
    return x  # type: ignore


def undisguise(x: Field[t.Any]) -> BFType:
    if isinstance(x, BFType):
        return x

    if isinstance(x, type):
        if is_bitfield_class(x):
            field_length = x.length()
            if field_length is None:
                raise TypeError("cannot infer length for dynamic Bitfield")
            return undisguise(bitfield_field(x, field_length))

        if issubclass(x, bool):
            return undisguise(bool_field())

    if isinstance(x, bytes):
        return undisguise(lit_bytes_field(default=x))

    if isinstance(x, str):
        return undisguise(lit_str_field(default=x))

    if x is None:
        return undisguise(none_field(default=None))

    raise TypeError(f"expected a field type, got {x!r}")


def uint_field(n: int, *, default: int | ellipsis = ...) -> Field[int]:
    """ An unsigned integer field type.

    Args:
        n (int): The number of bits used to represent the unsigned integer.
        default (int | ellipsis): An optional default value to use when constructing the field in a new object.

    Returns:
        Field[int]: A field that represents an unsigned integer.

    Example:
        ```python
        import bydantic as bd

        class Foo(bd.Bitfield):
            a: int = bd.uint_field(4)
            b: int = bd.uint_field(4, default=0)

        foo = Foo(a=1, b=2)
        print(foo) # Foo(a=1, b=2)
        print(foo.to_bytes()) # b'\\x12'

        foo2 = Foo.from_bytes_exact(b'\\x34')
        print(foo2) # Foo(a=3, b=4)

        foo3 = Foo(a = 1) # b is set to 0 by default
        print(foo3) # Foo(a=1, b=0)
        print(foo3.to_bytes()) # b'\\x10'
        ```
    """

    d = ellipsis_to_not_provided(default)

    if is_provided(d):
        if d < 0:
            raise ValueError(
                f"expected default to be non-negative, got {d}"
            )
        if is_int_too_big(d, n, signed=False):
            raise ValueError(
                f"expected default to fit in {n} bits, got {d}"
            )
    return disguise(BFUInt(n, d))


def int_field(n: int, *, default: int | ellipsis = ...) -> Field[int]:
    """ A signed integer field type.

    Args:
        n (int): The number of bits used to represent the signed integer.
        default (int | ellipsis): An optional default value to use when constructing the field in a new object.

    Returns:
        Field[int]: A field that represents a signed integer.

    Example:
        ```python
        import bydantic as bd

        class Foo(bd.Bitfield):
            a: int = bd.int_field(4)
            b: int = bd.int_field(4, default=-1)

        foo = Foo(a=1, b=-2)
        print(foo) # Foo(a=1, b=-2)
        print(foo.to_bytes()) # b'\\x16'

        foo2 = Foo.from_bytes_exact(b'\\x34')
        print(foo2) # Foo(a=3, b=4)

        foo3 = Foo(a = 1) # b is set to -1 by default
        print(foo3) # Foo(a=1, b=-1)
        print(foo3.to_bytes()) # b'\\x13'
        ```
    """

    d = ellipsis_to_not_provided(default)

    if is_provided(d):
        if is_int_too_big(d, n, signed=True):
            raise ValueError(
                f"expected signed default to fit in {n} bits, got {d}"
            )

    class ConvertSign:
        def forward(self, x: int) -> int:
            # x will always fit in n bits because it was
            # loaded by uint_field(n)

            if (x & (1 << (n - 1))) != 0:
                x -= 1 << n
            return x

        def back(self, y: int) -> int:
            if is_int_too_big(y, n, signed=True):
                raise ValueError(
                    f"expected signed value to fit in {n} bits, got {y}"
                )

            if y < 0:
                y += 1 << n
            return y

    return _bf_map_helper(uint_field(n), ConvertSign(), default=d)


def bool_field(*, default: bool | ellipsis = ...) -> Field[bool]:
    """ A boolean field type. (Bit flag)

    Args:
        default (bool | ellipsis): An optional default value to use when constructing the field in a new object.

    Returns:
        Field[bool]: A field that represents a boolean.

    Example:
        ```python
        import bydantic as bd

        class Foo(bd.Bitfield):
            a: bool = bd.bool_field()
            b: bool = bd.bool_field(default=True)
            _pad: int = bd.uint_field(6, default=0) # Pad to a full byte

        foo = Foo(a=True, b=False)
        print(foo) # Foo(a=True, b=False)
        print(foo.to_bytes()) # b'\\x80'

        foo2 = Foo.from_bytes_exact(b'\\x40')
        print(foo2) # Foo(a=False, b=True)

        foo3 = Foo(a = True) # b is set to True by default
        print(foo3) # Foo(a=True, b=True)
        print(foo3.to_bytes()) # b'\xc0'
        ```
    """
    class IntAsBool:
        def forward(self, x: int) -> bool:
            return x != 0

        def back(self, y: bool) -> int:
            return 1 if y else 0

    return _bf_map_helper(uint_field(1), IntAsBool(), default=ellipsis_to_not_provided(default))


def bytes_field(*, n_bytes: int, default: bytes | ellipsis = ...) -> Field[bytes]:
    """ A bytes field type.

    Args:
        n_bytes (int): The number of bytes in the field.
        default (bytes | ellipsis): An optional default value to use when constructing the field in a new object.

    Returns:
        Field[bytes]: A field that represents a sequence of bytes.

    Example:
        ```python
        import bydantic as bd

        class Foo(bd.Bitfield):
            a: bytes = bd.bytes_field(2)
            b: bytes = bd.bytes_field(2, default=b"yz")

        foo = Foo(a=b"xy", b=b"uv")
        print(foo) # Foo(a=b'xy', b=b'uv')

        foo2 = Foo.from_bytes_exact(b'xyuv')
        print(foo2) # Foo(a=b'xy', b=b'uv')

        foo3 = Foo(a = b"xy") # b is set to b"yz" by default
        print(foo3) # Foo(a=b'xy', b=b'yz')
        print(foo3.to_bytes()) # b'xyyz'
        ```
    """

    d = ellipsis_to_not_provided(default)

    if is_provided(d) and len(d) != n_bytes:
        raise ValueError(
            f"expected default bytes of length {n_bytes} bytes, got {len(d)} bytes ({d!r})"
        )

    class ListAsBytes:
        def forward(self, x: t.List[int]) -> bytes:
            return bytes(x)

        def back(self, y: bytes) -> t.List[int]:
            return list(y)

    return _bf_map_helper(list_field(uint_field(8), n_bytes), ListAsBytes(), default=d)


def str_field(*, n_bytes: int, encoding: str = "utf-8", default: str | ellipsis = ...) -> Field[str]:
    """ A string field type.

    Args:
        n_bytes (int): The number of bytes in the field.
        encoding (str): The encoding to use when converting the bytes to a string.
        default (str | ellipsis): An optional default value to use when constructing the field in a new object.

    Returns:
        Field[str]: A field that represents a string.

    Example:
        ```python
        import bydantic as bd

        class Foo(bd.Bitfield):
            a: str = bd.str_field(2)
            b: str = bd.str_field(2, default="yz")

        foo = Foo(a="xy", b="uv")
        print(foo) # Foo(a='xy', b='uv')

        foo2 = Foo.from_bytes_exact(b'xyuv')
        print(foo2) # Foo(a='xy', b='uv')

        foo3 = Foo(a = "xy") # b is set to "yz" by default
        print(foo3) # Foo(a='xy', b='yz')
        print(foo3.to_bytes()) # b'xyyz'
        ```
    """

    d = ellipsis_to_not_provided(default)

    if is_provided(d):
        byte_len = len(d.encode(encoding))
        if byte_len > n_bytes:
            raise ValueError(
                f"expected default string of maximum length {n_bytes} bytes, got {byte_len} bytes ({d!r})"
            )

    class BytesAsStr:
        def forward(self, x: bytes) -> str:
            return x.decode(encoding).rstrip("\0")

        def back(self, y: str) -> bytes:
            return y.ljust(n_bytes, "\0").encode(encoding)

    return _bf_map_helper(bytes_field(n_bytes=n_bytes), BytesAsStr(), default=d)


IntEnumT = t.TypeVar("IntEnumT", bound=IntEnum | IntFlag)


def uint_enum_field(n: int, enum: t.Type[IntEnumT], *, default: IntEnumT | ellipsis = ...) -> Field[IntEnumT]:
    """ An unsigned integer enum field type.

    Args:
        enum (Type[IntEnumT]): The enum class to use for the field. (Must be a subclass of IntEnum or IntFlag)
        n (int): The number of bits used to represent the enum.
        default (IntEnumT | ellipsis): An optional default value to use when constructing the field in a new object
            (Must match the enum type passed in the `enum` arg).

    Returns:
        Field[IntEnumT]: A field that represents an unsigned integer enum.

    Example:
        ```python
        import bydantic as bd
        from enum import IntEnum

        class Color(IntEnum):
            RED = 1
            GREEN = 2
            BLUE = 3
            PURPLE = 4

        class Foo(bd.Bitfield):
            a: Color = bd.uint_enum_field(4, Color)
            b: Color = bd.uint_enum_field(4, Color, default=Color.GREEN)

        foo = Foo(a=Color.RED, b=Color.BLUE)
        print(foo) # Foo(a=<Color.RED: 1>, b=<Color.BLUE: 3>)
        print(foo.to_bytes()) # b'\\x13'

        foo2 = Foo.from_bytes_exact(b'\\x24')
        print(foo2) # Foo(a=<Color.GREEN: 2>, b=<Color.PURPLE: 4>)

        foo3 = Foo(a = Color.RED) # b is set to Color.GREEN by default
        print(foo3) # Foo(a=<Color.RED: 1>, b=<Color.GREEN: 2>)
        print(foo3.to_bytes()) # b'\\x12'
        ```
    """

    if any(i.value < 0 for i in list(enum)):
        raise ValueError(
            "enum values in an unsigned int enum must be non-negative"
        )

    class IntAsEnum:
        def forward(self, x: int) -> IntEnumT:
            return enum(x)

        def back(self, y: IntEnumT) -> int:
            return y.value

    return _bf_map_helper(uint_field(n), IntAsEnum(), default=ellipsis_to_not_provided(default))


def int_enum_field(n: int, enum: t.Type[IntEnumT], *, default: IntEnumT | ellipsis = ...) -> Field[IntEnumT]:
    """ An signed integer enum field type.

    Args:
        n (int): The number of bits used to represent the enum.
        enum (Type[IntEnumT]): The enum class to use for the field. (Must be a subclass of IntEnum or IntFlag)
        default (IntEnumT | ellipsis): An optional default value to use when constructing the field in a new object
            (Must match the enum type passed in the `enum` arg).

    Returns:
        Field[IntEnumT]: A field that represents an unsigned integer enum.

    Example:
        ```python
        import bydantic as bd
        from enum import IntEnum

        class Color(IntEnum):
            RED = -2
            GREEN = -1
            BLUE = 0
            PURPLE = 1

        class Foo(bd.Bitfield):
            a: Color = bd.int_enum_field(4, Color)
            b: Color = bd.int_enum_field(4, Color, default=Color.GREEN)

        foo = Foo(a=Color.RED, b=Color.BLUE)
        print(foo) # Foo(a=<Color.RED: -2>, b=<Color.BLUE: 0>)
        print(foo.to_bytes()) # b'\\xe0'

        foo2 = Foo.from_bytes_exact(b'\\xfe')
        print(foo2) # Foo(a=<Color.GREEN: -1>, b=<Color.RED: -2>)
        ```
    """
    class IntAsEnum:
        def forward(self, x: int) -> IntEnumT:
            return enum(x)

        def back(self, y: IntEnumT) -> int:
            return y.value

    return _bf_map_helper(int_field(n), IntAsEnum(), default=ellipsis_to_not_provided(default))


def none_field(*, default: None | ellipsis = ...) -> Field[None]:
    """ A field type that represents no data.

    This field type is most useful when paired with `dynamic_field` to create
    optional values in a Bitfield.

    Args:
        default (None | ellipsis): The optional default value to use when constructing
            the field in a new object.

    Returns:
        Field[None]: A field that represents no data.

    Example:
        ```python
        import bydantic as bd

        class Foo(bd.Bitfield):
            a: int = bd.uint_field(8)
            b: int | None = bd.dynamic_field(lambda x: bd.uint_field(8) if x.a else bd.none_field())

        foo = Foo.from_bytes_exact(b'\\x01\\x02')
        print(foo) # Foo(a=1, b=2)

        foo2 = Foo.from_bytes_exact(b'\\x00')
        print(foo2) # Foo(a=0, b=None)

        ```
    """
    return disguise(BFNone(default=ellipsis_to_not_provided(default)))


def bits_field(n: int, *, default: t.Sequence[bool] | ellipsis = ...) -> Field[t.Tuple[bool, ...]]:
    """ A field type that represents a sequence of bits. (A tuple of booleans).

    Args:
        n (int): The number of bits in the field.
        default (t.Sequence[bool] | ellipsis): An optional default value to use when
            constructing the field in a new object. 

    Returns:
        Field[t.Tuple[bool, ...]]: A field that represents a sequence of bits.

    Example:
        ```python
        import bydantic as bd
        import typing as t

        class Foo(bd.Bitfield):
            a: t.Tuple[bool, ...] = bd.bits_field(4)
            b: t.Tuple[bool, ...] = bd.bits_field(4, default=(True, False, True, False))

        foo = Foo(a=(True, False, True, False), b=(False, True, False, True))
        print(foo) # Foo(a=(True, False, True, False), b=(False, True, False, True))
        print(foo.to_bytes()) # b'\\xaa\\xaa'

        foo2 = Foo.from_bytes_exact(b'\\xaa\\xaa')
        print(foo2) # Foo(a=(True, False, True, False), b=(False, True, False, True))

        foo3 = Foo(a=(True, False, True, False)) # b is set to (True, False, True, False) by default
        print(foo3) # Foo(a=(True, False, True, False), b=(True, False, True, False))
        print(foo3.to_bytes()) # b'\\xaa\\xaa'
        ```
    """
    return disguise(BFBits(n, ellipsis_to_not_provided(default)))


def bitfield_field(
    cls: t.Type[BitfieldT],
    n: int | ellipsis = ..., *,
    default: BitfieldT | ellipsis = ...
) -> Field[BitfieldT]:
    """ A field type that represents a Bitfield.

    Args:
        cls (t.Type[BitfieldT]): The Bitfield class to use for the field.
        n (int | ellipsis): The number of bits in the field. Note: this is optional
            for non-dynamic bitfields because it can inferred from the class itself.
        default (BitfieldT | ellipsis): An optional default value to use when constructing
            the field in a new object.

    Returns:
        Field[BitfieldT]: A field that represents a Bitfield.

    Example:
        ```python
        import bydantic as bd

        class Foo(bd.Bitfield):
            a: int = bd.uint_field(4)
            b: int = bd.uint_field(4, default=0)

        class Bar(bd.Bitfield):
            c: Foo = bd.bitfield_field(Foo, 8)

        bar = Bar(c=Foo(a=1, b=2))
        print(bar) # Bar(c=Foo(a=1, b=2))
        print(bar.to_bytes()) # b'\\x12\\x02'

        bar2 = Bar.from_bytes_exact(b'\\x12\\x02')
        print(bar2) # Bar(c=Foo(a=1, b=2))

        bar3 = Bar(c=Foo(a=1)) # c is set to Foo(a=1, b=0) by default
        print(bar3) # Bar(c=Foo(a=1, b=0))
        print(bar3.to_bytes()) # b'\\x10\\x00'

        # For non-dynamic bitfields, the size can be inferred:
        class Baz(bd.Bitfield):
            c: Foo = bd.bitfield_field(Foo)

        baz = Baz(c=Foo(a=1, b=2))
        print(baz) # Baz(c=Foo(a=1, b=2))
        print(baz.to_bytes()) # b'\\x12\\x02'
        ```
    """

    if n is ...:
        cls_length = cls.length()
        if cls_length is None:
            raise TypeError("cannot infer length for dynamic Bitfield")
        n = cls_length

    return disguise(BFBitfield(cls, n, default=ellipsis_to_not_provided(default)))


def _lit_field_helper(
    field: Field[T],
    *,
    default: P
) -> Field[P]:
    return disguise(BFLit(undisguise(field), default))


LiteralIntT = t.TypeVar("LiteralIntT", bound=int)
LiteralBytesT = t.TypeVar("LiteralBytesT", bound=bytes)
LiteralStrT = t.TypeVar("LiteralStrT", bound=str)


def lit_uint_field(n: int, *, default: LiteralIntT) -> Field[LiteralIntT]:
    """ A literal unsigned integer field type.

    Args:
        n (int): The number of bits used to represent the unsigned integer.
        default (LiteralIntT): The literal default value to use when constructing the field in a new object.
            (Required to infer the literal type).

    Returns:
        Field[LiteralIntT]: A field that represents a literal unsigned integer.

    Example:
        ```python
        import bydantic as bd
        import typing as t

        class Foo(bd.Bitfield):
            a: t.Literal[1] = bd.lit_uint_field(4, default=1)
            b: t.Literal[2] = bd.lit_uint_field(4, default=2)

        foo = Foo()
        print(foo) # Foo(a=1, b=2)
        print(foo.to_bytes()) # b'\\x12'

        foo2 = Foo.from_bytes_exact(b'\\x12')
        print(foo2) # Foo(a=1, b=2)
        ```
    """
    if default < 0:
        raise ValueError(
            f"expected default to be non-negative, got {default}"
        )
    if is_int_too_big(default, n, signed=False):
        raise ValueError(
            f"expected default to fit in {n} bits, got {default}"
        )
    return _lit_field_helper(uint_field(n), default=default)


def lit_int_field(n: int, *, default: LiteralIntT) -> Field[LiteralIntT]:
    """ A literal signed integer field type.

    Args:
        n (int): The number of bits used to represent the signed integer.
        default (LiteralIntT): The literal default value to use when constructing the field in a new object.
            (Required to infer the literal type).

    Returns:
        Field[LiteralIntT]: A field that represents a literal signed integer.

    Example:
        ```python
        import bydantic as bd
        import typing as t

        class Foo(bd.Bitfield):
            a: t.Literal[-1] = bd.lit_int_field(4, default=-1)
            b: t.Literal[2] = bd.lit_int_field(4, default=2)

        foo = Foo()
        print(foo) # Foo(a=-1, b=2)
        print(foo.to_bytes()) # b'\\xf2'

        foo2 = Foo.from_bytes_exact(b'\\xf2')
        print(foo2) # Foo(a=-1, b=2)
        ```
    """
    if is_int_too_big(default, n, signed=True):
        raise ValueError(
            f"expected signed default to fit in {n} bits, got {default}"
        )
    return _lit_field_helper(int_field(n), default=default)


def lit_bytes_field(
    *, default: LiteralBytesT
) -> Field[LiteralBytesT]:
    """ A literal bytes field type.

    Args:
        default (LiteralBytesT): The literal default value to use when constructing the field in a new object.
            (Required to infer the literal type).

    Returns:
        Field[LiteralBytesT]: A field that represents a literal bytes.

    Example:
        ```python
        import bydantic as bd
        import typing as t

        class Foo(bd.Bitfield):
            a: t.Literal[b'xy'] = bd.lit_bytes_field(default=b'xy')
            b: t.Literal[b'uv'] = bd.lit_bytes_field(default=b'uv')

        foo = Foo()
        print(foo) # Foo(a=b'xy', b=b'uv')
        print(foo.to_bytes()) # b'xyuv'

        foo2 = Foo.from_bytes_exact(b'xyuv')
        print(foo2) # Foo(a=b'xy', b=b'uv')

        # Note that the following shortcut may be alternatively used
        # in definitions:

        class Shortcut(bd.Bitfield):
            a: t.Literal[b'xy'] = b'xy'
            b: t.Literal[b'uv'] = b'uv'
        ```
    """
    return _lit_field_helper(bytes_field(n_bytes=len(default)), default=default)


def lit_str_field(
    *, encoding: str = "utf-8", default: LiteralStrT
) -> Field[LiteralStrT]:
    """ A literal string field type.

    Args:
        default (LiteralStrT): The literal default value to use when constructing the field in a new object.
            (Required to infer the literal type).

    Returns:
        Field[LiteralStrT]: A field that represents a literal string.

    Example:
        ```python
        import bydantic as bd
        import typing as t

        class Foo(bd.Bitfield):
            a: t.Literal["xy"] = bd.lit_str_field(encoding="utf-8", default="xy")
            b: t.Literal["uv"] = bd.lit_str_field(default="uv")

        foo = Foo()
        print(foo) # Foo(a='xy', b='uv')
        print(foo.to_bytes()) # b'xyuv'

        foo2 = Foo.from_bytes_exact(b'xyuv')
        print(foo2) # Foo(a="xy", b="uv")

        # Note that the following shortcut may be alternatively used
        # in definitions:

        class Shortcut(bd.Bitfield):
            a: t.Literal["xy"] = "xy"
            b: t.Literal["uv"] = "uv"
        ```
    """
    return _lit_field_helper(
        str_field(n_bytes=len(default.encode(encoding)), encoding=encoding),
        default=default
    )


def list_field(
    item: t.Type[T] | Field[T],
    n_items: int, *,
    default: t.List[T] | ellipsis = ...
) -> Field[t.List[T]]:
    """ A field type that represents a list of items.

    Args:
        item (t.Type[T] | Field[T]): The type of items in the list. In addition to fields,
            Bitfield classes can also be used here (provided they are non-dynamic).
        n_items (int): The number of items in the list.
        default (t.List[T] | ellipsis): An optional default value to use when constructing
            the field in a new object.

    Returns:
        Field[t.List[T]]: A field that represents a list of items.

    Example:
        ```python
        import bydantic as bd
        import typing as t

        class Foo(bd.Bitfield):
            a: int = bd.uint_field(4)
            b: t.List[int] = bd.list_field(bd.uint_field(4), 3, default=[1, 2, 3])

        foo = Foo(a=1, b=[0, 1, 2])
        print(foo) # Foo(a=1, b=[0, 1, 2])
        print(foo.to_bytes()) # b'\\x10\\x12'

        foo2 = Foo.from_bytes_exact(b'\\x10\\x12')
        print(foo2) # Foo(a=1, b=[0, 1, 2])

        foo3 = Foo(a=1) # b is set to [1, 2, 3] by default
        print(foo3) # Foo(a=1, b=[1, 2, 3])
        print(foo3.to_bytes()) # b'\\x11#'
        ```
    """

    d = ellipsis_to_not_provided(default)

    if is_provided(d) and len(d) != n_items:
        raise ValueError(
            f"expected default list of length {n_items}, got {len(d)} ({d!r})"
        )
    return disguise(BFList(undisguise(item), n_items, d))


def map_field(
    field: Field[T],
    vm: ValueMapper[T, P], *,
    default: P | ellipsis = ...
) -> Field[P]:
    """ A field type for creating transformations of values.

    Transformations are done via the `ValueMapper` protocol, an object
    defined with `forward` and `back` methods. The `forward` method
    is used to transform the value when deserializing the field from
    bytes, and the `back` method is used to reverse this transformation
    when serializing the field back to bytes.

    Several built-in value mappers are provided, including `Scale` and
    `IntScale`, for scaling values by a given float or int factor, respectively.

    Args:
        field (Field[T]): The field to transform.
        vm (ValueMapper[T, P]): The value mapper to use for the transformation.
        default (P | ellipsis): An optional default value to use when constructing
            the field in a new object.

    Returns:
        Field[P]: A field that represents the transformed value.

    Example:
        ```python
        import bydantic as bd
        import typing as t

        class Foo(bd.Bitfield):
            a: int = bd.uint_field(4)
            b: float = bd.map_field(
                bd.uint_field(4),
                bd.Scale(0.5),
                default=0.5
            )

        foo = Foo(a=1, b=1.5)
        print(foo) # Foo(a=1, b=1.5)
        print(foo.to_bytes()) # b'\\x13'

        foo2 = Foo.from_bytes_exact(b'\\x13')
        print(foo2) # Foo(a=1, b=1.5)

        foo3 = Foo(a=1) # b is set to 0.5 by default
        print(foo3) # Foo(a=1, b=0.5)
        print(foo3.to_bytes()) # b'\\x11'
        ```



    """
    return disguise(BFMap(undisguise(field), vm, ellipsis_to_not_provided(default)))


def _bf_map_helper(
    field: Field[T],
    vm: ValueMapper[T, P], *,
    default: P | NotProvided = NOT_PROVIDED,
) -> Field[P]:
    if is_provided(default):
        return map_field(field, vm, default=default)
    else:
        return map_field(field, vm)


def dynamic_field(
    fn: t.Callable[[t.Any], t.Type[T] | Field[T]] |
        t.Callable[[t.Any, int], t.Type[T] | Field[T]], *,
    default: T | ellipsis = ...
) -> Field[T]:
    n_params = len(inspect.signature(fn).parameters)
    match n_params:
        case 1:
            fn = t.cast(
                t.Callable[[t.Any], t.Type[T] | Field[T]],
                fn
            )
            return disguise(BFDynSelf(fn, default))
        case 2:
            fn = t.cast(
                t.Callable[
                    [t.Any, int], t.Type[T] | Field[T]
                ], fn
            )
            return disguise(BFDynSelfN(fn, default))
        case _:
            raise ValueError(f"unsupported number of parameters: {n_params}")


ContextT = TypeVarDefault("ContextT", default=None)


@dataclass()
class BitfieldConfig:
    reorder_bits: t.Sequence[int] = dataclass_field(default_factory=list)


@dataclass_transform(
    kw_only_default=True,
    field_specifiers=(
        uint_field,
        int_field,
        lit_uint_field,
        lit_int_field,
        bool_field,
        bytes_field,
        str_field,
        uint_enum_field,
        int_enum_field,
        none_field,
        bits_field,
        bitfield_field,
        _lit_field_helper,
        list_field,
        dynamic_field,
        map_field,
    )
)
class Bitfield(t.Generic[ContextT]):
    __bydantic_fields__: t.ClassVar[t.Dict[str, BFType]] = {}
    bitfield_config: t.ClassVar[BitfieldConfig] = BitfieldConfig()
    __BYDANTIC_CONTEXT_STR__: t.ClassVar[str] = "bitfield_context"
    bitfield_context: ContextT | None = None

    def __init__(self, **kwargs: t.Any):
        for name, field in self.__bydantic_fields__.items():
            value = kwargs.get(name, NOT_PROVIDED)

            if not is_provided(value):
                if is_provided(field.default):
                    value = field.default
                else:
                    raise ValueError(f"missing value for field {name!r}")

            setattr(self, name, value)

    def __repr__(self) -> str:
        return "".join((
            self.__class__.__name__,
            "(",
            ', '.join(
                f'{name}={getattr(self, name)!r}' for name in self.__bydantic_fields__
            ),
            ")",
        ))

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, self.__class__):
            return False

        return all((
            getattr(self, name) == getattr(other, name) for name in self.__bydantic_fields__
        ))

    @classmethod
    def length(cls) -> int | None:
        acc = 0
        for field in cls.__bydantic_fields__.values():
            field_len = bftype_length(field)
            if field_len is None:
                return None
            acc += field_len
        return acc

    @classmethod
    def from_bits_exact(cls, bits: t.Sequence[bool], opts: ContextT | None = None):
        out, remaining = cls.from_bits(bits, opts)

        if remaining:
            raise ValueError(
                f"Bits left over after parsing {cls.__name__} ({len(remaining)})"
            )

        return out

    @classmethod
    def from_bytes_exact(cls, data: t.ByteString, opts: ContextT | None = None):
        out, remaining = cls.from_bytes(data, opts)

        if remaining:
            raise ValueError(
                f"Bytes left over after parsing {cls.__name__} ({len(remaining)})"
            )

        return out

    @classmethod
    def from_bits(cls, bits: t.Sequence[bool], opts: ContextT | None = None) -> t.Tuple[Self, t.Tuple[bool, ...]]:
        out, stream = cls.__bydantic_read_stream__(
            BitstreamReader.from_bits(bits), opts
        )
        return out, stream.as_bits()

    @classmethod
    def from_bytes(cls, data: t.ByteString, opts: ContextT | None = None) -> t.Tuple[Self, bytes]:
        out, stream = cls.__bydantic_read_stream__(
            BitstreamReader.from_bytes(data), opts
        )
        return out, stream.as_bytes()

    @classmethod
    def from_bytes_batch(
        cls,
        data: t.ByteString,
        opts: ContextT | None = None,
        consume_errors: bool = False
    ) -> t.Tuple[t.List[Self], bytes]:
        out: t.List[Self] = []

        stream = BitstreamReader.from_bytes(data)

        while stream.bits_remaining():
            try:
                item, stream = cls.__bydantic_read_stream__(stream, opts)
                out.append(item)
            except DeserializeFieldError as e:
                if isinstance(e.inner, EOFError):
                    break

                if consume_errors:
                    _, stream = stream.take_bytes(1)
                else:
                    raise

            if not stream.bits_remaining() % 8:
                raise ValueError(
                    f"expected byte alignment, got {stream.bits_remaining()} bits"
                )

        return out, stream.as_bytes()

    def to_bits(self, opts: ContextT | None = None) -> t.Tuple[bool, ...]:
        return self.__bydantic_write_stream__(BitstreamWriter(), opts).as_bits()

    def to_bytes(self, opts: ContextT | None = None) -> bytes:
        return self.__bydantic_write_stream__(BitstreamWriter(), opts).as_bytes()

    def __init_subclass__(cls):
        cls.__bydantic_fields__ = cls.__bydantic_fields__.copy()

        curr_frame = inspect.currentframe()
        parent_frame = curr_frame.f_back if curr_frame else None
        parent_locals = parent_frame.f_locals if parent_frame else None

        for name, type_hint in t.get_type_hints(cls, localns=parent_locals).items():
            if t.get_origin(type_hint) is t.ClassVar or name == cls.__BYDANTIC_CONTEXT_STR__:
                continue

            value = getattr(cls, name) if hasattr(cls, name) else NOT_PROVIDED

            try:
                bf_field = _distill_field(type_hint, value)

                if bftype_has_children_with_default(bf_field):
                    raise ValueError(
                        f"inner field definitions cannot have defaults set (except literal fields)"
                    )
            except Exception as e:
                # Don't need to create an exception stack here (as we do for field errors)
                # because child bitfields must be defined first, so any errors will not
                # be nested
                raise type(e)(
                    f"in definition of '{cls.__name__}.{name}': {str(e)}"
                ) from e

            cls.__bydantic_fields__[name] = bf_field

    @classmethod
    def __bydantic_read_stream__(
        cls,
        stream: BitstreamReader,
        opts: ContextT | None,
    ):
        proxy: AttrProxy = AttrProxy({cls.__BYDANTIC_CONTEXT_STR__: opts})

        stream = stream.reorder(cls.bitfield_config.reorder_bits)

        for name, field in cls.__bydantic_fields__.items():
            try:
                value, stream = _read_bftype(
                    stream, field, proxy, opts
                )
            except DeserializeFieldError as e:
                e.push_stack(cls.__name__, name)
                raise
            except Exception as e:
                raise DeserializeFieldError(e, cls.__name__, name) from e

            proxy[name] = value

        return cls(**proxy), stream

    def __bydantic_write_stream__(
        self,
        stream: BitstreamWriter,
        opts: ContextT | None,
    ) -> BitstreamWriter:
        proxy = AttrProxy(
            {**self.__dict__, self.__BYDANTIC_CONTEXT_STR__: opts})

        for name, field in self.__bydantic_fields__.items():
            value = getattr(self, name)
            try:
                stream = _write_bftype(
                    stream, field, value, proxy, opts
                )
            except SerializeFieldError as e:
                e.push_stack(self.__class__.__name__, name)
                raise
            except Exception as e:
                raise SerializeFieldError(
                    e, self.__class__.__name__, name
                ) from e

        return stream.unreorder(self.bitfield_config.reorder_bits)


def _read_bftype(
    stream: BitstreamReader,
    bftype: BFType,
    proxy: AttrProxy,
    opts: t.Any
) -> t.Tuple[t.Any, BitstreamReader]:
    match bftype:
        case BFBits(n=n):
            return stream.take(n)

        case BFUInt(n=n):
            return stream.take_uint(n)

        case BFList(inner=inner, n=n):
            acc: t.List[t.Any] = []
            for _ in range(n):
                item, stream = _read_bftype(
                    stream, inner, proxy, opts
                )
                acc.append(item)
            return acc, stream

        case BFMap(inner=inner, vm=vm):
            value, stream = _read_bftype(
                stream, inner, proxy, opts
            )
            return vm.forward(value), stream

        case BFDynSelf(fn=fn):
            return _read_bftype(stream, undisguise(fn(proxy)), proxy, opts)

        case BFDynSelfN(fn=fn):
            return _read_bftype(stream, undisguise(fn(proxy, stream.bits_remaining())), proxy, opts)

        case BFLit(inner=inner, default=default):
            value, stream = _read_bftype(
                stream, inner, proxy, opts
            )
            if value != default:
                raise ValueError(
                    f"expected literal {default!r}, got {value!r}"
                )
            return value, stream

        case BFNone():
            return None, stream

        case BFBitfield(inner=inner, n=n):
            substream, stream = stream.take_stream(n)

            value, substream = inner.__bydantic_read_stream__(substream, opts)

            if substream.bits_remaining():
                raise ValueError(
                    f"expected Bitfield of length {n}, got {n - substream.bits_remaining()}"
                )

            return value, stream


def _write_bftype(
    stream: BitstreamWriter,
    bftype: BFType,
    value: t.Any,
    proxy: AttrProxy,
    opts: t.Any
) -> BitstreamWriter:
    match bftype:
        case BFBits(n=n):
            if len(value) != n:
                raise ValueError(f"expected {n} bits, got {len(value)}")
            return stream.put(value)

        case BFUInt(n=n):
            if not isinstance(value, int):
                raise TypeError(
                    f"expected int, got {type(value).__name__}"
                )
            return stream.put_uint(value, n)

        case BFList(inner=inner, n=n):
            if len(value) != n:
                raise ValueError(f"expected {n} items, got {len(value)}")
            for item in value:
                stream = _write_bftype(
                    stream, inner, item, proxy, opts
                )
            return stream

        case BFMap(inner=inner, vm=vm):
            first_arg = next(iter(inspect.signature(vm.back).parameters))
            expected_type = t.get_type_hints(
                vm.back
            ).get(first_arg, NOT_PROVIDED)

            # If the first arg of the mappers transform has a type hint,
            # check that the value is of that type
            #
            # (But exclude numbers, because the implicit conversions allowed
            # by the type hints are hard to check here)
            if is_provided(expected_type) and isinstance(expected_type, t.Type):

                if (
                    not isinstance(value, expected_type) and
                    not issubclass(expected_type, numbers.Number)
                ):
                    raise TypeError(
                        f"expected {expected_type.__name__}, got {type(value).__name__}"
                    )

            return _write_bftype(stream, inner, vm.back(value), proxy, opts)

        case BFDynSelf(fn=fn):
            return _write_bftype(stream, undisguise(fn(proxy)), value, proxy, opts)

        case BFDynSelfN(fn=fn):
            if is_bitfield(value):
                return value.__bydantic_write_stream__(stream, opts)

            if isinstance(value, (bool, bytes)) or value is None:
                return _write_bftype(stream, undisguise(value), value, proxy, opts)

            raise TypeError(
                f"dynamic fields that use discriminators with 'n bits remaining' "
                f"can only be used with Bitfield, bool, bytes, or None values. "
                f"{value!r} is not supported"
            )

        case BFLit(inner=inner, default=default):
            if value != default:
                raise ValueError(f"expected {default!r}, got {value!r}")
            return _write_bftype(stream, inner, value, proxy, opts)

        case BFNone():
            if value is not None:
                raise ValueError(f"expected None, got {value!r}")
            return stream

        case BFBitfield(inner=inner, n=n):
            if not is_bitfield(value):
                raise TypeError(
                    f"expected Bitfield, got {type(value).__name__}"
                )
            if value.length() is not None and value.length() != n:
                raise ValueError(
                    f"expected Bitfield of length {n}, got {value.length()}"
                )
            return value.__bydantic_write_stream__(stream, opts)


def _distill_field(type_hint: t.Any, value: t.Any) -> BFType:
    if not is_provided(value):
        if isinstance(type_hint, type) and issubclass(type_hint, (Bitfield, bool)):
            return undisguise(type_hint)

        if t.get_origin(type_hint) is t.Literal:
            args = t.get_args(type_hint)

            if len(args) != 1:
                raise TypeError(
                    f"literal must have exactly one argument"
                )

            return undisguise(args[0])

        raise TypeError(f"missing field definition")

    return undisguise(value)


BitfieldT = t.TypeVar("BitfieldT", bound=Bitfield)


def is_bitfield(x: t.Any) -> t.TypeGuard[Bitfield[t.Any]]:
    return isinstance(x, Bitfield)


def is_bitfield_class(x: t.Type[t.Any]) -> t.TypeGuard[t.Type[Bitfield[t.Any]]]:
    return issubclass(x, Bitfield)
