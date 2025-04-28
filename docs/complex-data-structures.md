# Complex Data Structures

In the [previous chapter](more-field-types.md), we encountered our first field
type combinator, `mapped_field`, which allowed us to apply a transformation to a
field type when serializing and deserializing the bitfield.

In general, field type combinators are field types that let you compose existing
field types into new field types. In this chapter we'll introduce three
additional field type combinators: `list_field`, `bitfield_field`, and
`dynamic_field`, and show how they can be used to create more complex data
structures.

## `list_field`

The `list_field` combinator allows you to define a field that contains a list of
values of a given field type. For example, the following will define a field
that contains a list of three `uint4` values:

```python
import bydantic as bd

class Foo(bd.BitField):
    my_list: list[int] = bd.list_field(bd.uint_field(4), 3)
```

As a field type combinator, any field type can be used as the base field type.
The following will define a field that contains a list of three two-byte chunks:

```python
import bydantic as bd

class Foo(bd.BitField):
    chunks: list[bytes] = bd.list_field(bd.bytes_field(n_bytes = 2), 3)
```

Don't forget that field type combinators are also field types, so they can be
used as the base field type in a `list_field`! For example, the following will
define a field that contains a list of three 8-bit temperature readings,
transformed to a `float` via a `mapped_field()` (as we did in the
[last chapter](more-field-types.md)):

```python
import bydantic as bd

class Foo(bd.BitField):
    temperature_readings: list[float] = bd.list_field(
        bd.mapped_field(bd.uint_field(8), bd.Scale(0.5, -40)), 3
    )
```

## `bitfield_field`

The `bitfield_field` combinator allows you to define a field using an existing
bitfield as the base field type. For example, the following will define a field
that will combine the two weather station packet types we defined in the the
previous chapters ([Getting Started](getting-started.md) and
[More Field Types](more-field-types.md)) into a single bitfield:

```python
import bydantic as bd

class ComboPacket(bd.BitField):
    packet1: WeatherPacket = bd.bitfield_field(WeatherPacket)
    packet2: WeatherPacket2 = bd.bitfield_field(WeatherPacket2)
```

Combined with the `list_field` combinator, we it's easy to define a bitfield
that contains a list of three packets of each type:

```python
import bydantic as bd

class ComboPacketList(bd.BitField):
    packets1: list[WeatherPacket] = bd.list_field(
        bd.bitfield_field(WeatherPacket), 3
    )
    packets2: list[WeatherPacket2] = bd.list_field(
        bd.bitfield_field(WeatherPacket2), 3
    )
```

In the case when the bitfield's size is known ahead of time (i.e. it doesn't
contain any `dynamic_field` definitions, which we will cover next), the
`bitfield_field` definition is optional. The following is equivalent to the
definitions above:

```python
import bydantic as bd

class ComboPacket(bd.BitField):
    packet1: WeatherPacket
    packet2: WeatherPacket

class ComboPacketList(bd.BitField):
    packets1: list[WeatherPacket] = bd.list_field(WeatherPacket, 3)
    packets2: list[WeatherPacket2] = bd.list_field(WeatherPacket2, 3)
```

## `dynamic_field`

The `dynamic_field` combinator allows you to define a field that can be chosen
at runtime based on the already-parsed values of the bitfield. `dynamic_field`s
are defined by way of a "discriminator" function. This discriminator function
will be called with the partially-parsed bitfield, and should return the field
type to use to parse the field.

For example, the following defines a bitfield named `DynamicFoo` with two
fields. The first field is a 1-bit enum field of type `PayloadType`, with
possible values `0: INT` and `1: STR`. The second field is either a `uint8` or a
`str` type field, depending on the value of the first field:

```python
from __future__ import annotations
import bydantic as bd

class PayloadType(Enum):
    INT = 0
    STR = 1

def discriminator(field: DynamicFoo) -> bd.Field[int | str]:
    match PayloadType:
        case PayloadType.INT:
            return bd.uint_field(8)
        case PayloadType.STR:
            return bd.str_field(n_bytes = 8)

class DynamicFoo(bd.BitField):
    payload_type: PayloadType = bd.uint_enum_field(PayloadType, 1)
    payload: int | str = bd.dynamic_field(discriminator)
```

Here's what it looks like when we deserialize a `DynamicFoo` bitfield:

```python
DynamicFoo.from_bytes_exact(b'\x00A')
# DynamicFoo(
#     payload_type=PayloadType.INT,
#     payload=65
# )

DynamicFoo.from_bytes_exact(b'\x01A')
# DynamicFoo(
#     payload_type=PayloadType.STR,
#     payload='A'
# )
```

In addition to returning fields of different types, discriminator functions can
return fields of different sizes. This is useful for dynamically-sized fields,
such as variable-length strings:

```python
from __future__ import annotations
import bydantic as bd

def discriminator(field: VarStr) -> bd.Field[str]:
    return bd.str_field(n_bytes = field.n_value_bytes)

class VarStr(bd.BitField):
    n_value_bytes: int = bd.uint_field(8)
    value: str = bd.dynamic_field(discriminator)
```

Here's some deserialization examples of the `VarStr` bitfield:

```python
VarStr.from_bytes_exact(b'\x02AB')
# VarStr(
#     n_value_bytes=2,
#     value='AB'
# )

VarStr.from_bytes_exact(b'\x03ABC')
# VarStr(
#     n_value_bytes=3,
#     value='ABC'
# )
```

The `dynamic_field` combinator is also useful for defining optional fields:

```python
from __future__ import annotations
import bydantic as bd

def discriminator(field: OptionalField) -> bd.Field[bytes | None]:
    if field.has_values:
        return bd.bytes_field(n_bytes = 8)
    else:
        return None

class OptionalField(bd.Bitfield):
    has_values: bool = bd.bool_field()
    values: bytes | None = bd.dynamic_field(discriminator)
```

## `dynamic_field` (discriminator variation 2)

Discriminator functions can also include a second argument, which will be passed
the number of bits remaining in the stream. For example, the following bitfield
definition will parse a bitfield if the remaining number of bits matches the
length of the bitfield, or a `bytes` field otherwise:

```python
from __future__ import annotations
import bydantic as bd

class ChildField(bd.Bitfield):
    a: int = bd.uint_field(8)
    b: int = bd.uint_field(8)
    c: int = bd.uint_field(8)

def discriminator(
    field: VarStr,
    n_bits_remaining: int
) -> bd.Field[ChildField | bytes]:

    if n_bits_remaining == ChildField.length():
        return ChildField
    else:
        return bd.bytes_field(n_bytes = n_bits_remaining // 8)


class FancyDynamic(bd.Bitfield):
    value: ChildField | bytes = bd.dynamic_field(discriminator)
```

Here's some deserialization examples of the `FancyDynamic` bitfield:

```python
FancyDynamic.from_bytes_exact(b'\x00\x00\x00\x00')
# FancyDynamic(
#     value=b'\x00\x00\x00\x00'
# )

FancyDynamic.from_bytes_exact(b'\x00\x00\x00')
# FancyDynamic(
#   value=ChildField(a=0, b=0, c=0)
# )
```

Note that when a `dynamic_field` uses a discriminator with `n_bits_remaining`,
only `Bitfield`, `bool`, `bytes`, or `None` values can be re-serialized (because
their bit length is known while serializing). If you create a `dynamic_field`
that uses `n_bits_remaining` and the discriminator function returns a field type
that is not one of these types, the `to_bytes()` method will raise an exception:

```python
from __future__ import annotations
import bydantic as bd

def discriminator(
    field: FailedDynamic,
    n_bits_remaining: int
) -> bd.Field[int | bytes]:

    if n_bits_remaining == 8:
        return bd.uint_field(8)
    else:
        return bd.bytes_field(n_bytes = n_bits_remaining // 8)

class FailedDynamic(bd.Bitfield):
    value: int | bytes = bd.dynamic_field(discriminator)

FailedDynamic.from_bytes_exact(b'\x00\x00\x00')
# FailedDynamic(
#     value=0
# )

FailedDynamic(value=0).to_bytes()
# bydantic.core.SerializeFieldError: TypeError in field
# 'FailedDynamic.value': dynamic fields that use discriminators
# with 'n bits remaining' can only be used with Bitfield, bool,
# bytes, or None values. 0 is not supported
```

This can be fixed by wrapping the `int` field in its own `Bitfield`, so that its
size is known when serializing:

```python
from __future__ import annotations
import bydantic as bd

class WrappedInt(bd.Bitfield):
    v: int = bd.uint_field(8)

def discriminator(
    field: FixedDynamic,
    n_bits_remaining: int
) -> bd.Field[WrappedInt | bytes]:

    if n_bits_remaining == 8:
        return WrappedInt
    else:
        return bd.bytes_field(n_bytes = n_bits_remaining // 8)

class FixedDynamic(bd.Bitfield):
    value: WrappedInt | bytes = bd.dynamic_field(discriminator)

FixedDynamic.from_bytes_exact(b'\x00')
# FixedDynamic(
#     value=WrappedInt(v=0)
# )

FixedDynamic(value=WrappedInt(v=0)).to_bytes()
# b'\x00'
```

## Putting It All Together

Let's see if we can put all these concepts together into a single example,
building on the `WeatherPacket` and `WeatherPacket2` bitfields we defined in the
previous chapters.

Say we have a controller device that collects weather data from a number of
weather stations, and then assembles the data into a single packet. Let's say it
gives us the number of weather stations in a 1-byte header, then a list of
weather packets. Each weather packet is in a container that contains a 1-byte
header indicating which weather packet version is used:

```python
from __future__ import annotations
import bydantic as bd
from enum import Enum

class WeatherPacketVersion(Enum):
    V1 = 0
    V2 = 1

def version_discriminator(
    field: WeatherPacketContainer
) -> bd.Field[WeatherPacket | WeatherPacket2]:

    if field.version == WeatherPacketVersion.V1:
        return WeatherPacket
    else:
        return WeatherPacket2

class WeatherPacketContainer(bd.BitField):
    version: WeatherPacketVersion = bd.uint_enum_field(WeatherPacketVersion, 8)
    packet: WeatherPacket | WeatherPacket2 = (
        bd.dynamic_field(version_discriminator)
    )

class WeatherControllerUpdate(bd.BitField):
    n_stations: int = bd.uint_field(8)
    packets: list[WeatherPacketContainer] = bd.list_field(
        WeatherPacketContainer, n_stations
    )
```

And there you have it!

## Next Steps

In this chapter, we introduced three new field type combinators: `list_field`,
`bitfield_field`, and `dynamic_field`, and showed how they can be used to create
more complex data structures.

The [next chapter](advanced-features.md) will cover some of bydantic's more
advanced features, but these features are still experimental and not necessary
to use the library.

This completes our tour of the field types and combinators available in
`bydantic`. Congratulations, now you can define bitfields like a pro!

For quick reference of field types and capabilities of the `Bitfield` class, you
can check out the [Field Type Reference](field-type-reference.md) and
[Bitfield Class Reference](bitfield-class-reference.md)
