# Global Context

As we saw in the [previous chapter](complex-data-structures), `dynamic_field`s
enable field types to be decided on the fly, based on the values of the fields
parsed so far, or by the number of bits remaining in the stream. In other words,
the field type of a `dynamic_field` can be determined by the local serialization
/ deserialization context.

It is also possible to pass an arbitrary _global_ context object to a bitfield
to use when serializaing or deserializing `dynamic_field`s. This feature can be
useful for situations when your bitfield may have different field types based on
the device's configuration, capabilities, or version of the firmware.

## A Simple Example: Customizing String Encoding

Let's look at a simple example, a bitfield that has the ability to customize its
string encoding based on the context passed when serializaing / deserializing
the bitfield:

```python
from __future__ import annotations
import typing as t
import bydantic as bd

# The custom context object that will be used in the bitfield
class FooSettings(t.NamedTuple):
    encoding: str

def discriminator(b: Foo):
    if b.ctx:
        return bd.str_field(n_bytes=6, encoding=b.ctx.encoding)
    else:
        return bd.str_field(n_bytes=6)

class Foo(bd.Bitfield[FooSettings]):
    bar: str = bd.dynamic_field(discriminator)
    baz: str = bd.dynamic_field(discriminator)
```

In this example, we define a `FooSettings` class that will be used as our global
context object when serializaing or deserializing the `Foo` bitfield, available
in the discriminator as `Foo.ctx`.

Here's what it looks like when we serialize and deserialize the `Foo` bitfield
using the `FooSettings` context:

```python
foo = Foo(bar = "hello", baz = "你好")

foo.to_bytes(ctx=FooSettings(encoding="utf-8"))
# b'hello\x00\xe4\xbd\xa0\xe5\xa5\xbd'

foo.to_bytes(ctx=FooSettings(encoding="GB2312"))
# b'hello\x00\xc4\xe3\xba\xc3\x00\x00'
```

Note that this class is passed as a type parameter to the `Bitfield` class, when
creating the `Foo` class -- this allows its type to be known in the
`discriminator` function (so when you press "." on the `ctx` field in your
discriminator you get all of the wonderful autocomplete features of your IDE).

## One More Example

Let's continue our running weather station theme from the previous chapters.
Here's a bitfield definition that allows you to enable / disable features of a
weather station protocol, depending on a global context object:

```python
from __future__ import annotations
import typing as t
import bydantic as bd

class WeatherStationFeatures(t.NamedTuple):
    n_temperature: t.Literal[6] | t.Literal[0]
    n_wind_speed: t.Literal[6] | t.Literal[0]

def temperature_discriminator(b: WeatherPacket3):
    if b.ctx:
        return bd.int_field(b.ctx.n_temperature) if b.ctx.n_temperature else None
    else:
        raise ValueError("ctx is required")

def wind_speed_discriminator(b: WeatherPacket3):
    if b.ctx:
        return bd.uint_field(b.ctx.n_wind_speed) if b.ctx.n_wind_speed else None
    else:
        raise ValueError("ctx is required")


def padding_discriminator(b: WeatherPacket3):
    if b.ctx:
        total_bits = b.ctx.n_temperature + b.ctx.n_wind_speed
        padding_needed = 8 - total_bits % 8 if total_bits % 8 else 0
        return bd.uint_field(padding_needed)
    else:
        raise ValueError("ctx is required")

class WeatherPacket3(bd.Bitfield[WeatherStationFeatures]):
    temperature: int | None = bd.dynamic_field(temperature_discriminator)
    wind_speed: int | None = bd.dynamic_field(wind_speed_discriminator)
    _pad: int = bd.dynamic_field(padding_discriminator, default = 0)
```

Here are a serialization / deserialization example:

```python
# A packet from a station with only temperature enabled:
WeatherPacket3(
    temperature=20,
    wind_speed=None,
).to_bytes(
    ctx=WeatherStationFeatures(
        n_temperature=6,
        n_wind_speed=0,
    )
)
# b'P'

WeatherPacket3.from_bytes_exact(
    b'P',
    ctx=WeatherStationFeatures(
        n_temperature=6,
        n_wind_speed=0,
    )
)
# WeatherPacket3(
#     temperature=20,
#     wind_speed=None,
#     _pad=0
# )
```

## Final Thoughts

Using global context with your bitfields is a powerful way to make your
bitfields configurable. That said, it can also make your code more complex, so
this feature should probably be used sparingly. If you find yourself using a lot
of global context, it may be a sign that you should consider making a separate
bitfield type for each configuration.

Global context is a newer feature in bydantic, so I would love to hear how you
are using it (or not using it) in your projects. If you have any feedback or
ideas, I'd love to hear from you! You can reach me at
[bydantic@kylehusmann.com](mailto: bydantic@kylehusmann.com).
