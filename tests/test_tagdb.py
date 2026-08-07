"""Jet4 compressed-unicode 解码测试。

这是点表读取里最容易出错的一环：`access_parser` 在这里是坏的，
实测毁掉 28% 的中文描述，所以本项目自带解码器并需要钉死行为。
"""

import pytest

from supcon_pic.tagdb import decode_jet4_text


def test_pure_ascii_stays_compressed():
    assert decode_jet4_text(b"P101_TH1_1") == "P101_TH1_1"


def test_pure_chinese_starts_uncompressed():
    # 首字节 0x00 立刻切到非压缩模式，其后每字符 2 字节 UTF-16LE
    assert decode_jet4_text(bytes.fromhex("00 8b53 9b52".replace(" ", ""))) == "压力"


def test_ascii_prefix_then_chinese():
    """真实样本：'DCS' + 0x00 切换 + UTF-16LE 中文。

    access_parser 对这条会输出 'DCS\\x00\\x9bOÙ~öeô\\x95¾\\x8b\\x9a[<P'。
    """
    raw = bytes.fromhex("44435300 9b4f d97e f665 f495 be8b 9a5b 3c50")
    assert decode_jet4_text(raw) == "DCS供给时间设定值"


def test_toggle_back_to_compressed():
    """中文之后再切回 ASCII——切换符可以出现多次。"""
    raw = bytes.fromhex("00 8b53 9b52 00".replace(" ", "")) + b"OK"
    assert decode_jet4_text(raw) == "压力OK"


def test_mixed_with_fullwidth_punctuation():
    raw = bytes.fromhex("00 f665 7065 3c50 08ff".replace(" ", "")) + b"\x00X5"
    assert decode_jet4_text(raw) == "时数值（X5"


def test_truncated_tail_dropped_not_crashing():
    """非压缩模式下末尾只剩半个码元时丢弃，不能抛异常。"""
    assert decode_jet4_text(bytes.fromhex("008b539b")) == "压"


def test_empty():
    assert decode_jet4_text(b"") == ""


@pytest.mark.parametrize("raw", [b"\x00", b"\x00\x00", b"\x00\x00\x00"])
def test_only_toggles_yield_empty(raw):
    assert decode_jet4_text(raw) == ""
