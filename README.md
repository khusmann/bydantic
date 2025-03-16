# Bydantic

[![Project Status: WIP – Initial development is in progress, but there has not yet been a stable, usable release suitable for the public.](https://www.repostatus.org/badges/latest/wip.svg)](https://www.repostatus.org/#wip)

Bydantic is a Python library for serializing and deserializing bitfields.
Bydantic allows you to declaratively define bitfields as Python classes with
type hints, which then can be automatically serialized and deserialized to and
from raw bytes.

The name Bydantic is a portmanteau of "bit" and "Pydantic" -- you can think of
Bydantic as a [Pydantic](https://docs.pydantic.dev) for serializing /
deserializing bitfields instead of validating raw objects.

## Installation

Bydantic is available on PyPI and can be installed using `pip`:

```bash
pip install bydantic
```

## Quick Start

Here's a simple example of Bydantic can be used:

```python
from bydantic import (
    Bitfield,
    bf_int,
    bf_str,
)

class Foo(Bitfield):
    a: int = bf_int(4)
    b: int = bf_int(4)
    c: str = bf_str(n_bytes=1)
```

This defines a bitfield with three fields: `a` and `b` are 4-bit integers, and
`c` is a 1-byte (8-bit) string. You can then serialize and deserialize instances
of `Foo` to and from raw bytes:

```python
foo = Foo(a=1, b=2, c="x")

# Serialize to bytes
print(foo.to_bytes()) # b'\x12x'

# Deserialize from bytes
foo2 = Foo.from_bytes_exact(b'\x34y')
print(foo2) # Foo(a=3, b=4, c='y')
```

The power of Bydantic, however, is that field types can be composed into complex
data structures. For example:

```python
from __future__ import annotations
import typing as t
from bydantic import (
    Bitfield,
    bf_int,
    bf_str,
    bf_dyn,
    bf_list,
)

class Foo(Bitfield):
    a: int = bf_int(4)
    b: int = bf_int(4)
    c: str = bf_str(n_bytes=1)


def discriminator(b: Bar):
    return bf_int(8) if b.d[0].a == 0 else bf_str(n_bytes=1)

class Bar(Bitfield):
    d: t.List[Foo] = bf_list(Foo, n_items = 2)
    e: int | str = bf_dyn(discriminator)

bar = Bar(d=[Foo(a=0, b=1, c="x"), Foo(a=2, b=3, c="y")], e=42)

# Serialize to bytes
print(bar.to_bytes()) # b'\x01x#y*'

# Deserialize from bytes
bar2 = Bar.from_bytes_exact(b'\x01x#y*')
print(bar2) # Bar(d=[Foo(a=0, b=1, c='x'), Foo(a=2, b=3, c='y')], e=42)
```

This just scratches the surface of what Bydantic can do... continue reading
[the docs](basic_field_types.md) for more info.

## Features

- Basic field types (e.g. `bf_int`, `bf_str`, `bf_bytes`, `bf_lit`, etc.)
- Field type combinators (e.g. `bf_list`, `bf_dyn`, `bf_map`, etc.)
- Serialization / deserialization context
- Bitfield reordering / alignment
- Clear error messages when fields fail to serialize / deserialize
