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
    wind_direction: WindDirection = bd.uint_enum_field(3, WindDirection)
    sensor_error: bool = bd.bool_field()
    _pad: t.Literal[0] = bd.lit_uint_field(4, default=0)
```

Before we dive into the details, let's serialize and deserialize a packets to
see it working:

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

## `_header`

The `_header` field was defined as follows:

```python
_header: t.Literal[b'\xFF'] = bd.lit_bytes_field(default = b'\xFF')
```
