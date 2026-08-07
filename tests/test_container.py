"""SDFF 容器与属性树解析的往返测试。"""

import struct

import pytest

from conftest import array, build_pic, byte, container, f64, i32, obj_list, str_list, stream, text
from sdff import SdffError, load, loads
from sdff.container import Array, parse_stream


def test_scalar_types_round_trip():
    raw = stream(
        i32("version", 12800)
        + f64("centerX", 1.5)
        + byte("bVisible", 1)
        + text("strTemplateName", "主产线背景模版.pic")
    )
    assert parse_stream(raw) == {
        "version": 12800,
        "centerX": 1.5,
        "bVisible": 1,
        "strTemplateName": "主产线背景模版.pic",
    }


def test_negative_int32():
    # beTile / layer 实测会取 -1，必须按有符号读
    assert parse_stream(stream(i32("layer", -1))) == {"layer": -1}


def test_string_list_collapses_to_list():
    raw = stream(str_list("texts", ["补水阀", "雾化器", "1#加料泵"]))
    assert parse_stream(raw) == {"texts": ["补水阀", "雾化器", "1#加料泵"]}


def test_named_container_stays_dict():
    raw = stream(container("PageInfo", i32("docWidth", 1920) + i32("docHeight", 960)))
    assert parse_stream(raw) == {"PageInfo": {"docWidth": 1920, "docHeight": 960}}


def test_nested_containers():
    """组合图元嵌套——只遍历顶层会漏图元，这里钉住嵌套能正确还原。"""
    inner = obj_list("shapes", [i32("id", 2) + text("clsid_name", "内层")])
    raw = stream(obj_list("lstShape", [i32("id", 1) + inner]))
    parsed = parse_stream(raw)
    assert parsed["lstShape"][0]["id"] == 1
    assert parsed["lstShape"][0]["shapes"][0]["clsid_name"] == "内层"


def test_array_has_flag_byte():
    """0x05 长度字段后有 1 字节 flag——漏掉会让后续解析整体偏移。"""
    data = struct.pack("<6i", 291, 819, 291, 892, 347, 892)
    raw = stream(array("arPoint", data, flag=0) + i32("bRotated", 7))
    parsed = parse_stream(raw)
    assert isinstance(parsed["arPoint"], Array)
    assert parsed["arPoint"].as_int32() == [291, 819, 291, 892, 347, 892]
    # 后续字段仍能正确读到，证明 flag 字节被消费了
    assert parsed["bRotated"] == 7


def test_array_float32():
    data = struct.pack("<3f", 0.25, 0.5, 0.75)
    parsed = parse_stream(stream(array("curveX", data)))
    assert parsed["curveX"].as_float32() == pytest.approx([0.25, 0.5, 0.75])


def test_container_size_includes_own_length_field_and_terminator():
    """容器 size 的口径：从长度字段自身起算，含末尾终止符。

    算错会让紧跟其后的字段解析错位——这是逆向时最耗时的坑。
    """
    body = container("group", i32("a", 1)) + i32("after", 42)
    parsed = parse_stream(stream(body))
    assert parsed == {"group": {"a": 1}, "after": 42}


def test_full_file_round_trip():
    pic = build_pic(
        {
            "DocInfo": stream(i32("version", 12800) + i32("fileType", 0)),
            "PageInfo": stream(i32("docWidth", 1920) + i32("docHeight", 960)),
            "Shape": stream(obj_list("lstShape", [i32("id", 1) + i32("clsid", 0)])),
            "Tag": stream(str_list("tag", ["P1_PT100101A01_PV"]) + str_list("ani", ["P1_1001YX.PV"])),
            "Text": stream(str_list("texts", ["喷雾干燥"])),
        }
    )
    doc = loads(pic, "synthetic.pic")
    assert doc.doc_info["version"] == 12800
    assert doc.page_info["docWidth"] == 1920
    assert doc.tags == {"tag": ["P1_PT100101A01_PV"], "ani": ["P1_1001YX.PV"]}
    assert doc.texts == ["喷雾干燥"]
    assert len(doc.shapes) == 1


def test_uncompressed_streams_supported():
    pic = build_pic({"DocInfo": stream(i32("version", 1))}, compress=False)
    assert loads(pic).doc_info == {"version": 1}


def test_missing_streams_yield_empty(tmp_path):
    """部分模板文件不含 Tag / Text，访问器应给空容器而不是 KeyError。"""
    path = tmp_path / "t.pic"
    path.write_bytes(build_pic({"DocInfo": stream(i32("version", 1))}))
    doc = load(path)
    assert doc.tags == {}
    assert doc.texts == []
    assert doc.shapes == []


def test_bad_magic_rejected():
    with pytest.raises(SdffError, match="bad magic"):
        loads(b"NOPE" + bytes(0x100))


def test_size_mismatch_rejected():
    pic = bytearray(build_pic({"DocInfo": stream(i32("version", 1))}))
    struct.pack_into("<Q", pic, 0x40 + 0x60, 999)  # 篡改声明的解压长度
    with pytest.raises(SdffError, match="header says 999"):
        loads(bytes(pic))


def test_unknown_type_rejected():
    with pytest.raises(SdffError, match="unknown type 0x7f"):
        parse_stream(stream(b"\x7f" + "x".encode() + b"\x00\x00\x00\x00\x00"))
