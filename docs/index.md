---
title: Welcome to bydantic
---

<!-- BEGIN CONTENT -->

# bydantic

[![Project Status: WIP – Initial development is in progress, but there has not yet been a stable, usable release suitable for the public.](https://www.repostatus.org/badges/latest/wip.svg)](https://www.repostatus.org/#wip)

`bydantic` is a Python library for serializing and deserializing bitfields.
bydantic allows you to declaratively define bitfields as Python classes with
type hints, which then can be automatically serialized and deserialized to and
from raw bytes.

The name bydantic is a portmanteau of "bit" and "pydantic" -- you can think of
bydantic as a [pydantic](https://docs.pydantic.dev)-like library for serializing
/ deserializing bitfields instead of validating raw objects.

## Installation

Clone this repository and run:

```bash
pip install .
```

I will publish this package to PyPI once it is more stable.

<!--
bydantic is available on PyPI and can be installed using `pip`:

```bash
pip install bydantic
```
-->

## Quick Start

Here's a simple example of how bydantic can be used:

```python
import bydantic as bd

class Foo(bd.Bitfield):
    a: int = bd.int_field(4)
    b: int = bd.int_field(4)
    c: str = bd.str_field(n_bytes=1)
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

The power of bydantic, however, is that field types can be composed into complex
data structures. For example:

```python
from __future__ import annotations
import bydantic as bd

class Foo(bd.Bitfield):
    a: int = bd.int_field(4)
    b: int = bd.int_field(4)
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
[the docs](basic_field_types.md) for more info.

## Features

- Basic field types (e.g. `int_field`, `str_field`, `bytes_field`, `lit_field`,
  etc.)
- Field type combinators (e.g. `list_field`, `dynamic_field`, `map_field`, etc.)
- Serialization / deserialization context
- Bitfield reordering / alignment
- Clear error messages when fields fail to serialize / deserialize, even when
  fields are deeply nested
