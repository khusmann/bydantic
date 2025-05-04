import pytest
import bydantic as bd
from bydantic.framing import SimpleFraming, BitfieldFramer

# Define KissFraming as an instance of SimpleFraming
kissFraming = SimpleFraming(
    delimiter=0xC0,
    escape_byte=0xDB,
    escape_map={
        0xC0: 0xDC,  # Frame delimiter
        0xDB: 0xDD,  # Escape byte
    },
)


def test_frame_data():
    frames = [
        b"\x01\x02\x03",
        b"\x04\x05\x06"
    ]

    framed_data = kissFraming.frame_data(frames)

    # Includes delimiter framing
    expected_framed_data = b"\xC0\x01\x02\x03\xC0\xC0\x04\x05\x06\xC0"

    assert framed_data == expected_framed_data


def test_unframe_data():
    data = b"\xC0\x01\x02\x03\xC0\xC0\x04\x05\x06\xC0"

    frames, remaining = kissFraming.unframe_data(data)

    assert frames == [b"\x01\x02\x03", b"\x04\x05\x06"]
    assert remaining == b""


def test_unframe_data_with_remaining():
    data = b"\xC0\x01\x02\x03\xC0\xC0\x04\x05\x06\xC0\xC0\x07\x08"

    frames, remaining = kissFraming.unframe_data(data)

    assert frames == [b"\x01\x02\x03", b"\x04\x05\x06"]
    assert remaining == b"\xC0\x07\x08"


def test_frame_data_with_escape():
    frames = [
        b"\x01\x02\xC0\x03",
        b"\x04\xDB\x05"
    ]

    framed_data = kissFraming.frame_data(frames)

    expected_framed_data = b"\xC0\x01\x02\xDB\xDC\x03\xC0\xC0\x04\xDB\xDD\x05\xC0"
    assert framed_data == expected_framed_data


def test_unframe_data_with_escaped_bytes():
    data = b"\xC0\x01\x02\xDB\xDC\x03\xC0\xC0\x04\xDB\xDD\x05\xC0"

    frames, remaining = kissFraming.unframe_data(data)

    assert frames == [b"\x01\x02\xC0\x03", b"\x04\xDB\x05"]
    assert remaining == b""


def test_unframe_data_invalid_escape():
    data = b"\xC0\x01\x02\xDB\xFF\x03\xC0"

    with pytest.raises(ValueError):
        kissFraming.unframe_data(data)


def test_framed_bitfield():
    class Foo(bd.Bitfield):
        a: int = bd.uint_field(4)
        b: int = bd.uint_field(4)

    data = b"\xC0\x12\xC0\xC0\x12\xC0\xC0\x12\xC0"

    framer = BitfieldFramer(Foo, kissFraming)

    foo = Foo(a=1, b=2)

    assert framer.to_bytes([foo, foo, foo]) == data

    frames, remaining = framer.from_bytes_batch(data + b"\xC0\x12")

    assert frames == [foo, foo, foo]
    assert remaining == b"\xC0\x12"
