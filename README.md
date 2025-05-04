# bydantic

[![Project Status: Active – The project has reached a stable, usable state and is being actively developed.](https://www.repostatus.org/badges/latest/active.svg)](https://www.repostatus.org/#active)
![PyPI - Version](https://img.shields.io/pypi/v/bydantic)
![PyPI - Downloads](https://img.shields.io/pypi/dm/bydantic)

`bydantic` is a Python library for serializing and deserializing bitfields.
bydantic allows you to declaratively define bitfields as Python classes with
type hints, which then can be automatically serialized and deserialized to and
from raw bytes.

The name bydantic is a portmanteau of "bit" and "pydantic" -- just as
[pydantic](https://docs.pydantic.dev) gives developers a way to declaratively
define data models with type hints and then serialize and deserialize raw
objects against those models, bydantic gives developers a way to do the same
with bitfields.

## Installation

bydantic is available on PyPI and can be installed using `pip`:

```bash
pip install bydantic
```

Note: Consider the current version as somewhat of a developer preview. bydantic
is still under active development, and the API is still not quite settled.

## Quick Start

Here's a simple example of how bydantic can be used:

```python
import bydantic as bd

class Foo(bd.Bitfield):
    a: int = bd.uint_field(4)
    b: int = bd.uint_field(4)
    c: str = bd.str_field(n_bytes=1)
```

This defines a bitfield with three fields: `a` and `b` are 4-bit unsigned
integers, and `c` is a 1-byte (8-bit) string:

![Bitfield Diagram](https://kylehusmann.com/bydantic/assets/example_foo.svg)

<!--

---
title: "Foo Bitfield"
---
%%{init: {'theme': 'default', 'packet': { 'rowHeight': 50, 'bitWidth': 100, 'bitsPerRow': 8 }}}%%
packet-beta
0-3: "a"
4-7: "b"
8-15: "c"

--->

You can then serialize and deserialize instances of `Foo` to and from raw bytes:

```python
foo = Foo(a=1, b=2, c="x")

# Serialize to bytes
print(foo.to_bytes()) # b'\x12x'

# Deserialize from bytes
foo2 = Foo.from_bytes_exact(b'\x34y')
print(foo2) # Foo(a=3, b=4, c='y')
```

The power of bydantic, however, is that field types can be composed into complex
data structures. For example:

```python
from __future__ import annotations
import bydantic as bd

class Foo(bd.Bitfield):
    a: int = bd.uint_field(4)
    b: int = bd.uint_field(4)
    c: str = bd.str_field(n_bytes=1)


def discriminator(b: Bar):
    return bd.int_field(8) if b.d[0].a == 0 else bd.str_field(n_bytes=1)

class Bar(bd.Bitfield):
    d: list[Foo] = bd.list_field(Foo, n_items = 2)
    e: int | str = bd.dynamic_field(discriminator)

bar = Bar(d=[Foo(a=0, b=1, c="x"), Foo(a=2, b=3, c="y")], e=42)

# Serialize to bytes
print(bar.to_bytes()) # b'\x01x#y*'

# Deserialize from bytes
bar2 = Bar.from_bytes_exact(b'\x01x#y*')
print(bar2) # Bar(d=[Foo(a=0, b=1, c='x'), Foo(a=2, b=3, c='y')], e=42)
```

This just scratches the surface of what bydantic can do... continue reading
[the docs](https://kylehusmann.com/bydantic/getting-started) for more info.

## Features

- [Field type primitives](https://kylehusmann.com/bydantic/field-type-reference#field-type-primitives)
  (e.g. `int_field`, `str_field`, `bytes_field`, etc.)
- [Field type combinators](https://kylehusmann.com/bydantic/field-type-reference#field-type-combinators)
  (e.g. `mapped_field`, `list_field`, `dynamic_field`, etc.)
- [Global serialization / deserialization context](https://kylehusmann.com/bydantic/global-context/)
- Clear error messages for serialization / deserialization failures, even when
  fields are deeply nested

## Related Projects

- [pydantic](https://docs.pydantic.dev)

- [bitproto](https://bitproto.readthedocs.io/)

- [bitstruct](https://bitstruct.readthedocs.io/)
