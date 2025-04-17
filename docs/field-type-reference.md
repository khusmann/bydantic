# Field Type Reference

## Field Type Primitives

bydantic comes with a variety of primitive field types that can be used to
define bitfields. From these primitives, more complex data structures can be
constructed via [field type combinators](#field-type-combinators).

### ::: bydantic.uint_field

### ::: bydantic.int_field

### ::: bydantic.bool_field

### ::: bydantic.bytes_field

### ::: bydantic.str_field

### ::: bydantic.uint_enum_field

### ::: bydantic.int_enum_field

### ::: bydantic.none_field

### ::: bydantic.bits_field

### ::: bydantic.bitfield_field

## Literal Field Types

These field types are used to define fields with literal types. They are most
often useful for fixed-length headers, padding, etc.

### ::: bydantic.lit_uint_field

### ::: bydantic.lit_int_field

### ::: bydantic.lit_bytes_field

### ::: bydantic.lit_str_field

## Field Type Combinators

These field types can be used build new field types from other field types.

### ::: bydantic.list_field

### ::: bydantic.mapped_field

### ::: bydantic.dynamic_field

## Value Mappers

`bydantic.mapped_field` uses the `ValueMapper` protocol for transforming values
when serializing and deserializing and deserializing bitfields. This section
describes the `ValueMapper` protocol and the built-in value mappers provided by
`bydantic`.

### ::: bydantic.ValueMapper

### ::: bydantic.Scale

### ::: bydantic.IntScale
