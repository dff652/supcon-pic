"""SUPCON 工程点表（`Control/CA*/CS*/Tag/Tags.mdb`）读取。

流程图只给位号字符串，中文描述、工程量程、单位和报警限都在点表里。
每个控制站一个 Tags.mdb，需要全部读进来才拿得到完整字典。

依赖可选的 `access_parser`（纯 Python 读 Access Jet DB）：
    pip install "supcon-pic[tagdb]"
"""

from __future__ import annotations

import contextlib
import glob
import os
from dataclasses import dataclass

#: 位号主表：位号名 + 中文描述 + 类型
TAGS_TABLE = "Tags"

#: 模拟量输入表，量程/单位/报警限都在这
AI_TABLE = "AI"

#: 点类型定义表，库内自带，是 Type_ID 的权威来源
TYPE_TABLE = "TagTypes"

#: Type_ID → 点类型名的兜底表（内容与实测 TagTypes 一致）。
#: 正常路径读库内 TagTypes；此表只在该表缺失时使用。
TYPE_NAMES = {
    1: "FB",   # 功能块
    2: "AI",   # 模拟量输入
    3: "AO",   # 模拟量输出
    4: "DI",   # 开关量输入
    5: "DO",   # 开关量输出
    6: "NA",   # 中间模拟量
    7: "ND",   # 中间开关量
    8: "NN",
    9: "PA",
    10: "PD",
    11: "PN",
}


@dataclass
class TagInfo:
    """一个位号的点表信息。"""

    name: str
    desc: str = ""
    type_id: int | None = None
    station: str = ""
    unit: str = ""
    range_low: float | None = None
    range_high: float | None = None
    #: 六级报警限 LLL/LL/L/H/HH/HHH，未组态的为 None
    limits: dict[str, float | None] = None
    #: 点类型名，由所属库的 TagTypes 表解析而来
    type_name: str = ""


def decode_jet4_text(buffer: bytes) -> str:
    """按 Jet4 compressed-unicode 规则解码文本列。

    Jet4 的字符串可以混合两种模式：压缩模式每字符 1 字节，非压缩模式每字符
    2 字节（UTF-16LE）。**`0x00` 字节是两种模式之间的切换符**，不是数据。

    `access_parser` 不认这个切换符——它把整段按 latin1 解出来再把 `0x00`
    统统删掉，于是所有「ASCII 前缀 + 中文」的描述全被毁掉：

        44 43 53 00 9b 4f d9 7e f6 65 f4 95 be 8b 9a 5b 3c 50
        access_parser -> 'DCS\\x00\\x9bOÙ~öeô\\x95¾\\x8b\\x9a[<P'
        正确解码      -> 'DCS供给时间设定值'

    实测受影响的行占 28%，且损坏不可从结果串反推（NUL 位置已丢失），
    所以必须在解码这一层修，不能事后补救。
    """
    out: list[str] = []
    index = 0
    compressed = True
    size = len(buffer)
    while index < size:
        byte = buffer[index]
        if byte == 0x00:  # 模式切换
            compressed = not compressed
            index += 1
        elif compressed:
            out.append(chr(byte))
            index += 1
        else:
            if index + 1 >= size:  # 截断的尾部，丢弃半个码元
                break
            out.append(chr(byte | (buffer[index + 1] << 8)))
            index += 2
    return "".join(out)


@contextlib.contextmanager
def _patched_text_decoding():
    """在 access_parser 的文本解码点上挂正确的 Jet4 解码器。

    作用域限定在读库期间，退出即还原——避免影响调用方其他地方对
    access_parser 的使用。
    """
    from access_parser import utils

    original = utils.get_decoded_text
    utils.get_decoded_text = decode_jet4_text
    try:
        yield
    finally:
        utils.get_decoded_text = original


def _column(table: dict, name: str, length: int):
    """按列名取值，列不存在时返回等长的 None 列表。"""
    return table.get(name) or [None] * length


def load_station(path: str) -> dict[str, TagInfo]:
    """读单个 Tags.mdb，返回 {位号名: TagInfo}。"""
    try:
        from access_parser import AccessParser
    except ImportError as exc:  # pragma: no cover - 依赖缺失路径
        raise ImportError(
            "读点表需要 access_parser：pip install 'supcon-pic[tagdb]'"
        ) from exc

    station = os.path.basename(os.path.dirname(os.path.dirname(path)))
    with _patched_text_decoding():
        return _read(AccessParser(path), station)


def _read(db, station: str) -> dict[str, TagInfo]:
    # 点类型名以库内 TagTypes 为准，缺表时才退到内置表。
    type_names = dict(TYPE_NAMES)
    try:
        types_table = db.parse_table(TYPE_TABLE)
        type_names.update(zip(types_table["Type_ID"], types_table["Type_Name"]))
    except Exception:  # noqa: BLE001 - 缺 TagTypes 不致命
        pass

    tags_table = db.parse_table(TAGS_TABLE)
    count = len(tags_table["Tag_Name"])
    out: dict[str, TagInfo] = {}
    by_property: dict[int, TagInfo] = {}
    for name, desc, type_id, property_id in zip(
        tags_table["Tag_Name"],
        _column(tags_table, "Tag_Desc", count),
        _column(tags_table, "Type_ID", count),
        _column(tags_table, "Property_ID", count),
    ):
        if not name:
            continue
        info = TagInfo(
            name=name,
            desc=desc or "",
            type_id=type_id,
            station=station,
            type_name=type_names.get(type_id, str(type_id)),
        )
        out[name] = info
        if property_id is not None:
            by_property[property_id] = info

    # AI 表按 Property_ID 挂回位号，补量程/单位/报警限。
    try:
        ai = db.parse_table(AI_TABLE)
    except Exception:  # noqa: BLE001 - 站里没有 AI 表是正常的
        return out
    n = len(ai.get("Property_ID", []))
    for idx, property_id in enumerate(ai.get("Property_ID", [])):
        info = by_property.get(property_id)
        if info is None:
            continue
        info.unit = _column(ai, "EU", n)[idx] or ""
        info.range_low = _column(ai, "SCL", n)[idx]
        info.range_high = _column(ai, "SCH", n)[idx]
        info.limits = {
            key: _column(ai, key, n)[idx] for key in ("LLL", "LL", "L", "H", "HH", "HHH")
        }
    return out


def load_project(root: str) -> dict[str, TagInfo]:
    """读整个解压后的 SUPCON_PROJECT 目录下所有控制站点表并合并。

    位号在全工程内唯一，重名时后读到的覆盖先读到的（实测无冲突）。
    """
    merged: dict[str, TagInfo] = {}
    paths = sorted(glob.glob(os.path.join(root, "**", "Tag", "Tags.mdb"), recursive=True))
    if not paths:
        raise FileNotFoundError(f"{root} 下没找到任何 */Tag/Tags.mdb")
    for path in paths:
        merged.update(load_station(path))
    return merged
