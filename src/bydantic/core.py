from __future__ import annotations

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
    """
    A protocol for transforming values during serialization / deserialization
    via [`map_field`](field-type-reference.md#bydantic.map_field).
    """

    def deserialize(self, x: T) -> P:
        """
        Transform the value from type T to type P when deserializing the bitfield.
        """
        ...

    def serialize(self, y: P) -> T:
        """
        Transform the value from type P to type T when serializing the bitfield.
        """
        ...


class Scale:
    """
    A value mapper that scales a value by a given factor,
    resulting in a float value.

    Attributes:
        by (float): The factor to scale by.
        n_digits (int | None): The number of digits to round to. If None, no rounding is done.
            Default is None.

    Example:
        ```python
        import bydantic as bd

        class Foo(bd.Bitfield):
            b: float = bd.map_field(bd.uint_field(8), bd.Scale(by=0.1))

        foo = Foo(b=2)
        print(foo) # Foo(b=0.2)

        foo2 = Foo.from_bytes_exact(b'\\x02')
        print(foo2) # Foo(b=0.2)
        ```
    """

    def __init__(self, by: float, offset: float = 0.0, n_digits: int | None = None):
        self.by = by
        self.offset = offset
        self.n_digits = n_digits

    def deserialize(self, x: int):
        value = x * self.by + self.offset
        return value if self.n_digits is None else round(value, self.n_digits)

    def serialize(self, y: float):
        return round((y - self.offset) / self.by)


class IntScale:
    """
    A value mapper that scales a value by a given factor,
    resulting in an integer value.

    Attributes:
        by (int): The factor to scale by.

    Example:
        ```python
        import bydantic as bd

        class Foo(bd.Bitfield):
            b: int = bd.map_field(bd.uint_field(8), bd.IntScale(by=10))

        foo = Foo(b=20)
        print(foo) # Foo(b=20)
        print(foo.to_bytes()) # b'\\x02'

        foo2 = Foo.from_bytes_exact(b'\\x02')
        print(foo2) # Foo(b=20)
        ```
    """

    def __init__(self, by: int, offset: int = 0):
        self.by = by
        self.offset = offset

    def deserialize(self, x: int):
        return x * self.by + self.offset

    def serialize(self, y: int):
        return round((y-self.offset) / self.by)


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
    """
    An unsigned integer field type.

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
    """
    A signed integer field type.

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
        def deserialize(self, x: int) -> int:
            # x will always fit in n bits because it was
            # loaded by uint_field(n)

            if (x & (1 << (n - 1))) != 0:
                x -= 1 << n
            return x

        def serialize(self, y: int) -> int:
            if is_int_too_big(y, n, signed=True):
                raise ValueError(
                    f"expected signed value to fit in {n} bits, got {y}"
                )

            if y < 0:
                y += 1 << n
            return y

    return _bf_map_helper(uint_field(n), ConvertSign(), default=d)


def bool_field(*, default: bool | ellipsis = ...) -> Field[bool]:
    """
    A boolean field type. (Bit flag)

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
        def deserialize(self, x: int) -> bool:
            return x != 0

        def serialize(self, y: bool) -> int:
            return 1 if y else 0

    return _bf_map_helper(uint_field(1), IntAsBool(), default=ellipsis_to_not_provided(default))


def bytes_field(*, n_bytes: int, default: bytes | ellipsis = ...) -> Field[bytes]:
    """
    A bytes field type.

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
        def deserialize(self, x: t.List[int]) -> bytes:
            return bytes(x)

        def serialize(self, y: bytes) -> t.List[int]:
            return list(y)

    return _bf_map_helper(list_field(uint_field(8), n_bytes), ListAsBytes(), default=d)


def str_field(*, n_bytes: int, encoding: str = "utf-8", default: str | ellipsis = ...) -> Field[str]:
    """
    A string field type.

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
        def deserialize(self, x: bytes) -> str:
            return x.rstrip(b"\0").decode(encoding)

        def serialize(self, y: str) -> bytes:
            return y.encode(encoding).ljust(n_bytes, b"\0")

    return _bf_map_helper(bytes_field(n_bytes=n_bytes), BytesAsStr(), default=d)


IntEnumT = t.TypeVar("IntEnumT", bound=IntEnum | IntFlag)


def uint_enum_field(enum: t.Type[IntEnumT], n: int,  *, default: IntEnumT | ellipsis = ...) -> Field[IntEnumT]:
    """
    An unsigned integer enum field type.

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
            a: Color = bd.uint_enum_field(Color, 4)
            b: Color = bd.uint_enum_field(Color, 4, default=Color.GREEN)

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
        def deserialize(self, x: int) -> IntEnumT:
            return enum(x)

        def serialize(self, y: IntEnumT) -> int:
            return y.value

    return _bf_map_helper(uint_field(n), IntAsEnum(), default=ellipsis_to_not_provided(default))


def int_enum_field(enum: t.Type[IntEnumT], n: int, *, default: IntEnumT | ellipsis = ...) -> Field[IntEnumT]:
    """
    An signed integer enum field type.

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
            a: Color = bd.int_enum_field(Color, 4)
            b: Color = bd.int_enum_field(Color, 4, default=Color.GREEN)

        foo = Foo(a=Color.RED, b=Color.BLUE)
        print(foo) # Foo(a=<Color.RED: -2>, b=<Color.BLUE: 0>)
        print(foo.to_bytes()) # b'\\xe0'

        foo2 = Foo.from_bytes_exact(b'\\xfe')
        print(foo2) # Foo(a=<Color.GREEN: -1>, b=<Color.RED: -2>)
        ```
    """
    class IntAsEnum:
        def deserialize(self, x: int) -> IntEnumT:
            return enum(x)

        def serialize(self, y: IntEnumT) -> int:
            return y.value

    return _bf_map_helper(int_field(n), IntAsEnum(), default=ellipsis_to_not_provided(default))


def none_field(*, default: None | ellipsis = ...) -> Field[None]:
    """
    A field type that represents no data.

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
    """
    A field type that represents a sequence of bits. (A tuple of booleans).

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
    """
    A field type that represents a Bitfield.

    Args:
        cls (t.Type[BitfieldT]): The Bitfield class to use for the field.
        n (int | ellipsis): The number of bits in the field. Note: this is optional
            for bitfields without dynamic fields because it can inferred from the class itself.
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

        # For bitfields without dynamic fields, the size can be inferred:
        class Baz(bd.Bitfield):
            c: Foo = bd.bitfield_field(Foo)

        # Or, more concisely:
        class Baz(bd.Bitfield):
            c: Foo

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


def lit_uint_field(n: int, *, default: T) -> Field[T]:
    """
    A literal unsigned integer field type.

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
    if not isinstance(default, int):
        raise TypeError(
            f"expected default to be an integer, got {default!r}"
        )
    if default < 0:
        raise ValueError(
            f"expected default to be non-negative, got {default}"
        )
    if is_int_too_big(default, n, signed=False):
        raise ValueError(
            f"expected default to fit in {n} bits, got {default}"
        )
    return _lit_field_helper(uint_field(n), default=default)


def lit_int_field(n: int, *, default: T) -> Field[T]:
    """
    A literal signed integer field type.

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
    if not isinstance(default, int):
        raise TypeError(
            f"expected default to be an integer, got {default!r}"
        )
    if is_int_too_big(default, n, signed=True):
        raise ValueError(
            f"expected signed default to fit in {n} bits, got {default}"
        )
    return _lit_field_helper(int_field(n), default=default)


def lit_bytes_field(
    *, default: T
) -> Field[T]:
    """
    A literal bytes field type.

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
    if not isinstance(default, bytes):
        raise TypeError(
            f"expected default to be bytes, got {default!r}"
        )
    return _lit_field_helper(bytes_field(n_bytes=len(default)), default=default)


def lit_str_field(
    *, n_bytes: int | None = None, encoding: str = "utf-8", default: T
) -> Field[T]:
    """
    A literal string field type.

    Args:
        n_bytes (int): The number of bytes used to represent the string.
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
    if not isinstance(default, str):
        raise TypeError(
            f"expected default to be str, got {default!r}"
        )

    if n_bytes is None:
        n_bytes = len(default.encode(encoding))

    return _lit_field_helper(
        str_field(n_bytes=n_bytes, encoding=encoding),
        default=default
    )


def list_field(
    item: t.Type[T] | Field[T],
    n_items: int, *,
    default: t.List[T] | ellipsis = ...
) -> Field[t.List[T]]:
    """
    A field type that represents a list of items.

    Args:
        item (t.Type[T] | Field[T]): The type of items in the list. In addition to fields,
            Bitfield classes can also be returned (provided they don't have dynamic fields).
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


def mapped_field(
    field: Field[T],
    vm: ValueMapper[T, P], *,
    default: P | ellipsis = ...
) -> Field[P]:
    """
    A field type for creating transformations of values.

    Transformations are done via the `ValueMapper` protocol, an object
    defined with `deserialize` and `serialize` methods. The `deserialize` method
    is used to transform the value when deserializing the field from
    the provided field type, and the `serialize` method is used to reverse this transformation
    when serializing the field back.

    Several built-in value mappers are provided, including
    [`Scale`](bitfield-class-reference.md#bydantic.Scale) and
    [`IntScale`](bitfield-class-reference.md#bydantic.IntScale),
    for scaling values by a given float or int factor, respectively.

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
        return mapped_field(field, vm, default=default)
    else:
        return mapped_field(field, vm)


def dynamic_field(
    fn: t.Callable[[t.Any], t.Type[T] | Field[T]] |
        t.Callable[[t.Any, int], t.Type[T] | Field[T]], *,
    default: T | ellipsis = ...
) -> Field[T]:
    """
    A field type that can be decided at runtime, based on the values of
    already-parsed fields, or the number of bits remaining in the stream.

    Note that the discriminator function provided can be either a one-argument or two-argument
    function. If a one-argument function is provided, it will be called with an intermeditate
    Bitfield object with the fields that have been parsed so far. If a two-argument function is
    the first argument will be the intermediate Bitfield object and the second
    argument will be the number of bits remaining in the stream. The function
    should use this information to return a valid field type to use for the field.

    Args:
        fn (t.Callable[[t.Any], t.Type[T] | Field[T]] | t.Callable[[t.Any, int], t.Type[T] | Field[T]])):
            A one or two-argument function that returns the field type to use for the field.
        default (T | ellipsis): An optional default value to use when constructing
            the field in a new object.

    Returns:
        Field[T]: A field that represents a dynamic field.

    Example:
        ```python
        import bydantic as bd
        import typing as t

        class Foo(bd.Bitfield):
            a: int = bd.uint_field(8)
            b: int | bytes = bd.dynamic_field(
                lambda x: bd.uint_field(8) if x.a else bd.bytes_field(n_bytes=1)
            )

        foo = Foo.from_bytes_exact(b'\\x01\\x02')
        print(foo) # Foo(a=1, b=2)

        foo2 = Foo.from_bytes_exact(b'\\x00A')
        print(foo2) # Foo(a=0, b=b'A')
        ```
    """
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


@dataclass_transform(
    kw_only_default=True,
    field_specifiers=(
        uint_field,
        int_field,
        lit_uint_field,
        lit_int_field,
        lit_bytes_field,
        lit_str_field,
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
        mapped_field,
    )
)
class Bitfield(t.Generic[ContextT]):
    """A base class for creating bitfields."""

    __bydantic_fields__: t.ClassVar[t.Dict[str, BFType]] = {}

    __BYDANTIC_CONTEXT_STR__: t.ClassVar[str] = "ctx"

    ctx: ContextT | None = None
    """
    A context object that can be referenced by dynamic fields while
    serializing and deserializing the bitfield. Set by `to_*` and
    `from_*` methods when serializing and deserializing the bitfield.
    """

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
        """
        Get the length of a bitfield in bits. If the bitfield has dynamic fields, `None`
        is returned.

        Returns:
            int | None: The length of the bitfield in bits, or `None` if it has dynamic fields.
        """
        acc = 0
        for field in cls.__bydantic_fields__.values():
            field_len = bftype_length(field)
            if field_len is None:
                return None
            acc += field_len
        return acc

    @classmethod
    def from_bits_exact(cls, bits: t.Sequence[bool], ctx: ContextT | None = None):
        """
        Parses a bitfield from a sequence of bits, returning the parsed object.
        Raises a ValueError if there are any bits left over after parsing.

        Args:
            bits (t.Sequence[bool]): The bits to parse.
            ctx (ContextT | None): An optional context object to use when parsing.

        Returns:
            Self: The parsed object.

        Raises:
            ValueError: If there are any bits left over after parsing.
        """
        out, remaining = cls.from_bits(bits, ctx)

        if remaining:
            raise ValueError(
                f"Bits left over after parsing {cls.__name__} ({len(remaining)})"
            )

        return out

    @classmethod
    def from_bytes_exact(cls, data: t.ByteString, ctx: ContextT | None = None):
        """
        Parses a bitfield from a byte string, returning the parsed object.
        Raises a ValueError if there are any bytes left over after parsing.

        Args:
            data (t.ByteString): The bytes to parse.
            ctx (ContextT | None): An optional context object to use when parsing.

        Returns:
            Self: The parsed object.

        Raises:
            ValueError: If there are any bytes left over after parsing.
        """
        out, remaining = cls.from_bytes(data, ctx)

        if remaining:
            raise ValueError(
                f"Bytes left over after parsing {cls.__name__} ({len(remaining)})"
            )

        return out

    @classmethod
    def from_bits(cls, bits: t.Sequence[bool], ctx: ContextT | None = None) -> t.Tuple[Self, t.Tuple[bool, ...]]:
        """
        Parse a bitfield from a sequence of bits, returning the parsed object and
        any remaining bits.

        Args:
            bits (t.Sequence[bool]): The bits to parse.
            ctx (ContextT | None): An optional context object to use when parsing.

        Returns:
            t.Tuple[Self, t.Tuple[bool, ...]]: A tuple containing the parsed object and
                any remaining bits.
        """
        out, stream = cls.__bydantic_read_stream__(
            BitstreamReader.from_bits(bits), ctx
        )
        return out, stream.as_bits()

    @classmethod
    def from_bytes(cls, data: t.ByteString, ctx: ContextT | None = None) -> t.Tuple[Self, bytes]:
        """ 
        Parses a bitfield from a byte string, returning the parsed object and
        any remaining bytes.

        Args:
            data (t.ByteString): The bytes to parse.
            ctx (ContextT | None): An optional context object to use when parsing.

        Returns:
            t.Tuple[Self, bytes]: A tuple containing the parsed object and
                any remaining bytes.
        """
        out, stream = cls.__bydantic_read_stream__(
            BitstreamReader.from_bytes(data), ctx
        )
        return out, stream.as_bytes()

    @classmethod
    def from_bytes_batch(
        cls,
        data: t.ByteString,
        ctx: ContextT | None = None,
    ) -> t.Tuple[t.List[Self], bytes]:
        """
        Parses a batch of bitfields from a byte string, returning the parsed objects
        and any remaining bytes.

        Args:
            data (t.ByteString): The bytes to parse.
            ctx (ContextT | None): An optional context object to use when parsing.

        Returns:
            t.Tuple[t.List[Self], bytes]: A tuple containing the parsed objects and
                any remaining bytes.
        """
        out: t.List[Self] = []

        stream = BitstreamReader.from_bytes(data)

        while stream.bits_remaining():
            try:
                item, stream = cls.__bydantic_read_stream__(stream, ctx)
                out.append(item)
            except DeserializeFieldError as e:
                if isinstance(e.inner, EOFError):
                    break
                else:
                    raise

            if not stream.bits_remaining() % 8:
                raise ValueError(
                    f"expected byte alignment, got {stream.bits_remaining()} bits"
                )

        return out, stream.as_bytes()

    def to_bits(self, ctx: ContextT | None = None) -> t.Tuple[bool, ...]:
        """
        Serializes the bitfield to a sequence of bits.

        Args:
            ctx (ContextT | None): An optional context object to use when serializing.

        Returns:
            t.Tuple[bool, ...]: The serialized bitfield as a sequence of bits.
        """
        return self.__bydantic_write_stream__(BitstreamWriter(), ctx).as_bits()

    def to_bytes(self, ctx: ContextT | None = None) -> bytes:
        """
        Serializes the bitfield to a byte string.

        Args:
            ctx (ContextT | None): An optional context object to use when serializing.

        Returns:
            bytes: The serialized bitfield as a byte string.
        """
        return self.__bydantic_write_stream__(BitstreamWriter(), ctx).as_bytes()

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
        ctx: ContextT | None,
    ):
        proxy: AttrProxy = AttrProxy({cls.__BYDANTIC_CONTEXT_STR__: ctx})

        for name, field in cls.__bydantic_fields__.items():
            try:
                value, stream = _read_bftype(
                    stream, field, proxy, ctx
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
        ctx: ContextT | None,
    ) -> BitstreamWriter:
        proxy = AttrProxy(
            {**self.__dict__, self.__BYDANTIC_CONTEXT_STR__: ctx})

        for name, field in self.__bydantic_fields__.items():
            value = getattr(self, name)
            try:
                stream = _write_bftype(
                    stream, field, value, proxy, ctx
                )
            except SerializeFieldError as e:
                e.push_stack(self.__class__.__name__, name)
                raise
            except Exception as e:
                raise SerializeFieldError(
                    e, self.__class__.__name__, name
                ) from e

        return stream


def _read_bftype(
    stream: BitstreamReader,
    bftype: BFType,
    proxy: AttrProxy,
    ctx: t.Any
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
                    stream, inner, proxy, ctx
                )
                acc.append(item)
            return acc, stream

        case BFMap(inner=inner, vm=vm):
            value, stream = _read_bftype(
                stream, inner, proxy, ctx
            )
            return vm.deserialize(value), stream

        case BFDynSelf(fn=fn):
            return _read_bftype(stream, undisguise(fn(proxy)), proxy, ctx)

        case BFDynSelfN(fn=fn):
            return _read_bftype(stream, undisguise(fn(proxy, stream.bits_remaining())), proxy, ctx)

        case BFLit(inner=inner, default=default):
            value, stream = _read_bftype(
                stream, inner, proxy, ctx
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

            value, substream = inner.__bydantic_read_stream__(substream, ctx)

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
    ctx: t.Any
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
                    stream, inner, item, proxy, ctx
                )
            return stream

        case BFMap(inner=inner, vm=vm):
            first_arg = next(iter(inspect.signature(vm.serialize).parameters))
            expected_type = t.get_type_hints(
                vm.serialize
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

            return _write_bftype(stream, inner, vm.serialize(value), proxy, ctx)

        case BFDynSelf(fn=fn):
            return _write_bftype(stream, undisguise(fn(proxy)), value, proxy, ctx)

        case BFDynSelfN(fn=fn):
            if is_bitfield(value):
                return value.__bydantic_write_stream__(stream, ctx)

            if isinstance(value, (bool, bytes)) or value is None:
                return _write_bftype(stream, undisguise(value), value, proxy, ctx)

            raise TypeError(
                f"dynamic fields that use discriminators with 'n bits remaining' "
                f"can only be used with Bitfield, bool, bytes, or None values. "
                f"{value!r} is not supported"
            )

        case BFLit(inner=inner, default=default):
            if value != default:
                raise ValueError(f"expected {default!r}, got {value!r}")
            return _write_bftype(stream, inner, value, proxy, ctx)

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
            return value.__bydantic_write_stream__(stream, ctx)


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
