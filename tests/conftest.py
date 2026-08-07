"""合成 SDFF 文件的构造器。

测试不依赖任何客户工程数据——按 docs/format-spec.md 反向生成字节，
再用解析器读回来比对。这同时也是规格的可执行文档。
"""

from __future__ import annotations

import struct
import zlib

ENCODING = "gbk"


def _name(text: str) -> bytes:
    return text.encode(ENCODING) + b"\x00"


def i32(name: str, value: int) -> bytes:
    return b"\x10" + _name(name) + struct.pack("<i", value)


def f64(name: str, value: float) -> bytes:
    return b"\x01" + _name(name) + struct.pack("<d", value)


def byte(name: str, value: int) -> bytes:
    return b"\x08" + _name(name) + bytes([value])


def text(name: str, value: str) -> bytes:
    payload = value.encode(ENCODING) + b"\x00"
    return b"\x02" + _name(name) + struct.pack("<I", len(payload)) + payload


def array(name: str, data: bytes, flag: int = 0) -> bytes:
    return b"\x05" + _name(name) + struct.pack("<I", len(data)) + bytes([flag]) + data


def container(name: str, children: bytes, tag: int = 0x04) -> bytes:
    # size 从长度字段自身起算，一直算到末尾的 0x00 终止符（含）
    size = 4 + len(children) + 1
    return bytes([tag]) + _name(name) + struct.pack("<I", size) + children + b"\x00"


def str_list(name: str, values: list[str]) -> bytes:
    """字符串列表，如 Text 流的 texts、Tag 流的 tag/ani。"""
    return container(name, b"".join(text(str(i), v) for i, v in enumerate(values)))


def obj_list(name: str, objects: list[bytes]) -> bytes:
    """对象列表，如 Shape 流的 lstShape。每个元素是一个 0x03 容器。"""
    return container(
        name, b"".join(container(str(i), obj, 0x03) for i, obj in enumerate(objects))
    )


def stream(records: bytes) -> bytes:
    total = 4 + len(records) + 1
    return struct.pack("<I", total) + records + b"\x00"


def build_pic(streams: dict[str, bytes], *, compress: bool = True) -> bytes:
    """把 {流名: 已编码的流字节} 组装成完整的 .pic 文件。"""
    header = bytearray(0x40)
    header[0:4] = b"SDFF"
    struct.pack_into("<I", header, 8, len(streams))
    struct.pack_into("<Q", header, 0x10, 0x01DC328_8EDAA1500 & 0xFFFFFFFFFFFFFFFF)
    header[0x18:0x28] = bytes(range(16))

    directory = bytearray()
    payload = bytearray()
    base = 0x1000  # 实测所有文件首个流都落在这里
    for name, raw in streams.items():
        entry = bytearray(0x80)
        encoded = name.encode("utf-16le")
        entry[0 : len(encoded)] = encoded
        blob = struct.pack("<I", len(raw)) + (zlib.compress(raw) if compress else raw)
        struct.pack_into("<Q", entry, 0x50, base + len(payload))
        struct.pack_into("<Q", entry, 0x58, 1 if compress else 0)
        struct.pack_into("<Q", entry, 0x60, len(raw))
        directory += entry
        payload += blob

    out = bytearray(header + directory)
    out += b"\x00" * (base - len(out))
    out += payload
    return bytes(out)
