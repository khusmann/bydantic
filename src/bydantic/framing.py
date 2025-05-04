import typing as t
from .core import BitfieldT


class FramingProtocol(t.Protocol):
    def unframe_data(self, data: bytes) -> t.Tuple[t.List[bytes], bytes]:
        ...

    def frame_data(self, frames: t.Sequence[bytes]) -> bytes:
        ...


class SimpleFraming:
    def __init__(
        self,
        delimiter: int,
        escape_byte: int,
        escape_map: t.Dict[int, int],
    ):
        self.delimiter = delimiter
        self.escape_byte = escape_byte
        self.escape_map = escape_map

    def unescape_frame(self, frame: t.ByteString) -> bytes:
        inverse_map = {v: k for k, v in self.escape_map.items()}
        unescaped = bytearray()
        i = 0
        while i < len(frame):
            byte = frame[i]
            if byte == self.escape_byte:
                i += 1
                if i >= len(frame):
                    break
                esc = frame[i]
                if esc not in inverse_map:
                    raise ValueError(
                        f"Invalid escape sequence: {self.escape_byte:02X} {esc:02X}"
                    )
                unescaped.append(inverse_map[esc])
            else:
                unescaped.append(byte)
            i += 1
        return bytes(unescaped)

    def unframe_data(self, data: bytes) -> t.Tuple[t.List[bytes], bytes]:
        frames: t.List[bytes] = []
        current_frame = bytearray()
        i = 0

        while i < len(data):
            byte = data[i]

            if byte == self.delimiter:
                if current_frame:
                    frames.append(self.unescape_frame(current_frame))
                    current_frame.clear()
                i += 1
            else:
                current_frame.append(byte)
                i += 1

        remaining = (
            bytes([self.delimiter]) + current_frame if current_frame else b""
        )

        return frames, remaining

    def frame_data(self, frames: t.Sequence[bytes]) -> bytes:
        output = bytearray()
        for frame in frames:
            output.append(self.delimiter)
            for byte in frame:
                if byte in (self.delimiter, self.escape_byte):
                    output.append(self.escape_byte)
                    output.append(self.escape_map[byte])
                else:
                    output.append(byte)
            output.append(self.delimiter)

        return bytes(output)


class BitfieldFramer(t.Generic[BitfieldT]):
    def __init__(
        self,
        bitfield: t.Type[BitfieldT],
        framing: FramingProtocol,
    ):
        self.bitfield = bitfield
        self.framing = framing

    def from_bytes_batch(self, data: bytes) -> t.Tuple[t.List[BitfieldT], bytes]:
        """
        Deserializes a batch of bitfields from a byte string, with framing.

        Args:
            data (bytes): The byte string to deserialize.

        Returns:
            t.Tuple[t.List[BitfieldT], bytes]: A tuple containing a list of
                deserialized bitfields and any remaining bytes.
        """
        frames, remaining = self.framing.unframe_data(data)
        bitfields = [self.bitfield.from_bytes_exact(frame) for frame in frames]
        return bitfields, remaining

    def to_bytes(self, data: t.Sequence[BitfieldT]) -> bytes:
        """
        Serializes the bitfield to a byte string, with framing.

        Args:
            data (BitfieldT): The bitfield to serialize.

        Returns:
            bytes: The serialized bitfield as a byte string.
        """
        raw_data = tuple(frame.to_bytes() for frame in data)
        return self.framing.frame_data(raw_data)
