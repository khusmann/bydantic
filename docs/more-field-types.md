# More Field Types

In the [previous chapter](getting-started.md), we considered a hypothetical
weather station packet. To introduce some more field types, let's imagine we've
upgraded our weather station to a new version with a different protocol, defined
as follows:

| Bits    | Field          | Type (N bits) | Description                                           |
| ------- | -------------- | ------------- | ----------------------------------------------------- |
| 0-7     | (Header)       | bytes (8)     | Packet header, always `0xFF`                          |
| 8-39    | Station UUID   | bytes (32)    | Unique identifier for the station (4 bytes)           |
| 40-103  | Station Name   | str (64)      | Name of the weather station (8 bytes)                 |
| 104-111 | Temperature    | float (8)     | Temperature, degrees Celsius (uint value \* 0.5 - 40) |
| 112-119 | Wind Speed     | float (8)     | Wind speed, m/h (uint value \* 0.25)                  |
| 120-122 | Wind Direction | enum (3)      | Wind direction (0 = N, 1 = NE, ..., 7 = NW)           |
| 123     | Sensor Error   | bool (1)      | Sensor error flag (1 = error)                         |
| 124-127 | (Pad)          | uint (4)      | Padding bits, always `0`                              |

With bydantic, definition can be translated into a Bitfield class that looks
like this:

```python
import typing as t
import bydantic as bd

class WindDirection(IntEnum):
    N = 0
    NE = 1
    E = 2
    SE = 3
    S = 4
    SW = 5
    W = 6
    NW = 7

class WeatherPacket2(bd.Bitfield):
    _header: t.Literal[b'\xFF'] = bd.lit_bytes_field(default = b'\xFF')
    station_uuid: bytes = bd.bytes_field(n_bytes = 4)
    station_name: str = bd.str_field(n_bytes = 8)
    temperature: float = bd.mapped_field(
        bd.uint_field(8),
        bd.Scale(by = 0.5, offset = -40)
    )
    wind_speed: float = bd.mapped_field(
        bd.uint_field(8),
        bd.Scale(by = 0.25)
    )
    wind_direction: WindDirection = bd.uint_enum_field(WindDirection, 3)
    sensor_error: bool = bd.bool_field()
    _pad: t.Literal[0] = bd.lit_uint_field(4, default=0)
```

Before we dive into the details, let's serialize and deserialize a packet to see
it in action:

```python
WeatherPacket2(
    station_uuid = b'\x00\x00\x00\x01',
    station_name = 'Foo',
    temperature = 25.0,
    wind_speed = 10.0,
    wind_direction = WindDirection.NE,
    sensor_error = False
).to_bytes()

# b'\xff\x00\x00\x00\x01Foo\x00\x00\x00\x00\x00\x82( '

WeatherPacket2.from_bytes_exact(
    b'\xff\x00\x00\x00\x01Foo\x00\x00\x00\x00\x00\x82( '
)
# WeatherPacket2(
#   _header=b'\xFF',
#   station_uuid=b'\x00\x00\x00\x01',
#   station_name='Foo',
#   temperature=25.0,
#   wind_speed=10.0,
#   wind_direction=WindDirection.NE,
#   sensor_error=False
#   _pad=0
```

Ok, it works! Now let's take a look at the definition, field by field.

## Field-by-field explanation

### `_header`

The `_header` field is defined as follows:

```python
_header: t.Literal[b'\xFF'] = bd.lit_bytes_field(default = b'\xFF')
```

This field is our first example of a literal field. Literal fields parse
constant values that result in `typing.Literal` field types. In this case, the
`_header` field is a literal field with a fixed value of `b'\xFF'`.

Here we use an underscore prefix in the field name (`_header`) and provide a
default value in the definition to indicate the field is private and not
necessary to provide when creating a new instance of the class.

In addition to `lit_bytes_field()`, other literal field types available in
bydantic include `lit_uint_field`, `lit_int_field`, and `lit_str_field`.

Because the size of a literal `bytes` or `str` field can be inferred from the
literal value, bydantic allows you to omit the `lit_bytes_field()` or
`lit_str_field()` call and simply use the value itself. So the following is
equivalent to the above definition of `_header`:

```python
_header: t.Literal[b'\xFF'] = b'\xFF'
```

### `station_uuid`

The `station_uuid` field is defined as follows:

```python
station_uuid: bytes = bd.bytes_field(n_bytes = 4)
```

This field is a `bytes` field with a size of 4 bytes. Not much to say here!

### `station_name`

The `station_name` field is defined as follows:

```python
station_name: str = bd.str_field(n_bytes = 8)
```

This field is a `str` field with a fixed width of 8 bytes. Fixed-width string
values are padded with null bytes (`b'\x00'`) to the specified size. The `str`
field is encoded using the `utf-8` encoding by default, but you can specify a
different encoding using the `encoding` parameter:

```python
station_name: str = bd.str_field(n_bytes = 8, encoding = 'latin-1')
```

### `temperature`, `wind_speed`

The `temperature` and `wind_speed` fields are defined as follows:

```python
temperature: float = bd.mapped_field(
    bd.uint_field(8),
    bd.Scale(by = 0.5, offset = -40)
)
wind_speed: float = bd.mapped_field(
    bd.uint_field(8),
    bd.Scale(by = 0.25)
)
```

These definitions introduce the `mapped_field()`, our first field combinator.
Field combinators are used to create new field types by combining existing field
types. The `mapped_field()` combinator takes two arguments: a field type and a
object conforming to the `ValueMapper` protocol, a protcol that defines how to
map that field type to and from a different type:

```python
import typing as t

T = t.TypeVar('T')
P = t.TypeVar('P')
class ValueMapper(t.Protocol[T, P]):
    def forward(self, value: T) -> P:
        ...

    def back(self, value: P) -> T:
        ...
```

Here, we're using `Scale`, a built-in `ValueMapper` defined in bydantic as
follows:

```python
class Scale:
    def __init__(self, by: float, offset: float = 0.0):
        self.by = by
        self.offset = offset

    def forward(self, value: float) -> int:
        return int((value - self.offset) / self.by)

    def back(self, value: int) -> float:
        return value * self.by + self.offset
```

In the case of `temperature`, we're using `Scale()` to map the `uint8` value to
a `float` value by scaling it by `0.5` and offsetting it by `-40`. So a value of
`0` in the `uint8` field will be mapped to `-40.0` in the `float` field, and a
value of `255` in the `uint8` field will be mapped to `127.5` in the `float`
field.

In the case of `wind_speed`, we're using `Scale()` to map the `uint8` value to a
`float` value by scaling it by `0.25`. So a value of `0` in the `uint8` field
will be mapped to `0.0` in the `float` field, and a value of `255` in the
`uint8` field will be mapped to `63.75` in the `float` field.

The `mapped_field()` combinator can be used with any field type, as long as you
provide a `ValueMapper` object that defines how to map the field type to and
from the target type. This allows you to easily create your own custom field
types.

### `wind_direction`, `sensor_error`

The `wind_direction` and `sensor_error` fields are defined as follows:

```python
wind_direction: WindDirection = bd.uint_enum_field(WindDirection, 3)
sensor_error: bool = bd.bool_field()
```

Both enum and bool fields were already covered in the
[previous chapter](getting-started.md), so we won't go into detail here.

### `_pad`

The `_pad` field is defined as follows:

```python
_pad: t.Literal[0] = bd.lit_uint_field(4, default=0)
```

Here is another example of a literal field. This field is a literal 4-bit `uint`
field with a fixed value of `0`. The `_pad` field is used to pad the packet to a
multiple of 8 bytes. Like the `_header` field, the `_pad` field is declared
private, and specifies a default value so it does not need to be provided when
creating a new instance of the class.

Unlike the `lit_bytes_field()` and `lit_str_field()` fields, the size of a
numeric literal field cannot be inferred from the literal value, so it is allows
necessary to specify the field type, and shortcuts are not allowed:

```python
# This will not work, because the number of
# bits cannot be determined from the value!
_pad: t.Literal[0] = 0
```

## Next Steps

In this chapter, we introduced some more field types along with our first field
combinator, `mapped_field()`. In the [next chapter](complex-data-structures.md),
we'll introduce some more field combinator types that allow you to compose your
definitions into more complex data structures.
