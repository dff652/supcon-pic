"""SDFF 容器与 TLV 属性树解析（纯 stdlib）。

SUPCON DCS 流程图 `.pic` 文件的底层格式，规格见 docs/format-spec.md。
本模块只负责「字节 → Python 对象」，不做任何领域解释。
"""

from __future__ import annotations

import datetime
import struct
import zlib
from typing import Any

MAGIC = b"SDFF"
HEADER_SIZE = 0x40
DIR_ENTRY_SIZE = 0x80

#: 已知流名。文件里出现顺序即目录顺序。
STREAM_NAMES = ("DocInfo", "PageInfo", "Shape", "Tag", "Text")

#: 属性树里字符串的编码。SUPCON 组态软件是简体中文 Windows 程序。
ENCODING = "gbk"


class SdffError(ValueError):
    """SDFF 文件结构不符合预期。"""


class Array:
    """type 0x05 原始字节块（坐标数组 / GUID / LOGFONT 等）。

    未做二次解释——语义随宿主字段变化，交给上层按 ``owner`` 决定怎么读。
    """

    __slots__ = ("flag", "data")

    def __init__(self, flag: int, data: bytes) -> None:
        self.flag = flag
        self.data = data

    def as_int32(self) -> list[int]:
        n = len(self.data) // 4
        return list(struct.unpack_from(f"<{n}i", self.data))

    def as_float32(self) -> list[float]:
        n = len(self.data) // 4
        return list(struct.unpack_from(f"<{n}f", self.data))

    def __len__(self) -> int:
        return len(self.data)

    def __repr__(self) -> str:
        return f"Array(flag={self.flag}, {len(self.data)}B)"


class Document:
    """一个 `.pic` 文件的全部内容。"""

    __slots__ = ("path", "streams", "created", "guid")

    def __init__(self, path, streams, created, guid) -> None:
        self.path = path
        self.streams = streams
        self.created = created
        self.guid = guid

    # 五个流的便捷访问；缺失时返回空容器而不是 KeyError,
    # 因为部分模板文件确实不含 Tag / Text。
    @property
    def doc_info(self) -> dict:
        return self.streams.get("DocInfo") or {}

    @property
    def page_info(self) -> dict:
        return self.streams.get("PageInfo") or {}

    @property
    def shapes(self) -> list:
        return (self.streams.get("Shape") or {}).get("lstShape", [])

    @property
    def tags(self) -> dict:
        return self.streams.get("Tag") or {}

    @property
    def texts(self) -> list:
        return (self.streams.get("Text") or {}).get("texts", [])

    def __repr__(self) -> str:
        return f"Document({self.path!r}, shapes={len(self.shapes)})"


def read_raw_streams(data: bytes) -> dict[str, bytes]:
    """解开容器与 zlib，返回 {流名: 解压后的字节}。"""
    if data[:4] != MAGIC:
        raise SdffError(f"bad magic {data[:4]!r}, expected {MAGIC!r}")
    count = struct.unpack_from("<I", data, 8)[0]
    out: dict[str, bytes] = {}
    for i in range(count):
        base = HEADER_SIZE + i * DIR_ENTRY_SIZE
        name = data[base : base + 0x40].decode("utf-16le").rstrip("\x00")
        offset, flag, usize = (
            struct.unpack_from("<Q", data, base + off)[0] for off in (0x50, 0x58, 0x60)
        )
        # 负载前 4 字节重复了未压缩长度，zlib 流紧随其后。
        if flag == 1:
            raw = zlib.decompress(data[offset + 4 :])
        else:
            raw = data[offset + 4 : offset + 4 + usize]
        if len(raw) != usize:
            raise SdffError(f"stream {name!r}: got {len(raw)} bytes, header says {usize}")
        out[name] = raw
    return out


def _parse_records(buf: bytes, pos: int, end: int) -> list[tuple[str, Any]]:
    items: list[tuple[str, Any]] = []
    while pos < end:
        tag = buf[pos]
        if tag == 0x00:  # 容器终止符，也用作尾部填充
            pos += 1
            continue
        pos += 1
        stop = buf.index(b"\x00", pos)
        name = buf[pos:stop].decode(ENCODING, "replace")
        pos = stop + 1

        if tag == 0x10:  # int32
            value = struct.unpack_from("<i", buf, pos)[0]
            pos += 4
        elif tag == 0x01:  # double
            value = struct.unpack_from("<d", buf, pos)[0]
            pos += 8
        elif tag == 0x08:  # byte / bool
            value = buf[pos]
            pos += 1
        elif tag == 0x02:  # 字符串：u32 字节数（含结尾 NUL）
            size = struct.unpack_from("<I", buf, pos)[0]
            pos += 4
            value = buf[pos : pos + size].split(b"\x00")[0].decode(ENCODING, "replace")
            pos += size
        elif tag == 0x05:  # 数组：u32 字节数 + 1 字节 flag + 裸数据
            size = struct.unpack_from("<I", buf, pos)[0]
            pos += 4
            value = Array(buf[pos], buf[pos + 1 : pos + 1 + size])
            pos += 1 + size
        elif tag in (0x03, 0x04):  # 容器
            # size 从自身长度字段起算，容器最后一个字节是 0x00 终止符。
            size = struct.unpack_from("<I", buf, pos)[0]
            value = _collapse(_parse_records(buf, pos + 4, pos + size - 1))
            pos += size
        else:
            raise SdffError(f"unknown type 0x{tag:02x} for field {name!r} at offset {pos}")
        items.append((name, value))
    return items


def _collapse(items: list[tuple[str, Any]]):
    """键全是十进制数字的容器还原成 list，其余成 dict。

    SUPCON 用 "0"/"1"/"2"… 表示数组元素（lstShape / texts / tag 都是这种）。
    """
    if items and all(key.isdigit() for key, _ in items):
        return [value for _, value in items]
    return dict(items)


def parse_stream(raw: bytes):
    """解析单个解压后的流。首 4 字节是流总长度。"""
    total = struct.unpack_from("<I", raw, 0)[0]
    return _collapse(_parse_records(raw, 4, min(total, len(raw)) - 1))


def loads(data: bytes, path: str | None = None) -> Document:
    """从字节解析一个 `.pic`。"""
    filetime = struct.unpack_from("<Q", data, 0x10)[0]
    created = datetime.datetime(1601, 1, 1) + datetime.timedelta(microseconds=filetime // 10)
    guid = data[0x18:0x28]
    streams = {name: parse_stream(raw) for name, raw in read_raw_streams(data).items()}
    return Document(path, streams, created, guid)


def load(path) -> Document:
    """从磁盘解析一个 `.pic`。"""
    with open(path, "rb") as fh:
        return loads(fh.read(), str(path))
