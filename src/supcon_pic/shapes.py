"""图元遍历与位号抽取。

`Shape` 流是一棵图元树：组合图元(Group)带 `shapes` 子列表，可嵌套。
绑定 DCS 位号的字段有两个——`strDLTag`（DataLink，绝大多数）与 `strTag`。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Iterator

#: 图元上承载位号的字段名。两个都要看，只看 strDLTag 会漏掉约 1% 的绑定。
TAG_FIELDS = ("strDLTag", "strTag")

#: DataLink 未绑定实时值时的占位内容，形如 "???.??"。
_PLACEHOLDER_CHARS = set("?.")


def iter_shapes(node: Any) -> Iterator[dict]:
    """深度优先遍历图元树，逐个 yield 图元 dict（含组合图元自身与其子图元）。"""
    if isinstance(node, dict):
        if "clsid" in node and "id" in node:
            yield node
        for key, value in node.items():
            if key in ("shapes", "lstShape"):
                yield from iter_shapes(value)
    elif isinstance(node, list):
        for value in node:
            yield from iter_shapes(value)


def bbox(shape: dict) -> tuple[int, int, int, int] | None:
    """图元包围盒。线性图元用 start/end，容器类用 left/top/right/bottom。"""
    if "startX" in shape:
        return (
            shape["startX"],
            shape["startY"],
            shape.get("endX", shape["startX"]),
            shape.get("endY", shape["startY"]),
        )
    if "left" in shape:
        return (shape["left"], shape["top"], shape["right"], shape["bottom"])
    return None


def center(box: tuple[int, int, int, int]) -> tuple[float, float]:
    return ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)


def shape_tag(shape: dict) -> str | None:
    for field_name in TAG_FIELDS:
        value = shape.get(field_name)
        if value:
            return value
    return None


def is_static_label(shape: dict) -> bool:
    """静态中文标签（有 content 且不是 DataLink 的 ??? 占位）。"""
    content = shape.get("content")
    if not content or shape_tag(shape):
        return False
    return bool(set(content) - _PLACEHOLDER_CHARS)


@dataclass
class TagBinding:
    """流程图上一处位号绑定。"""

    page: str
    tag: str
    shape_name: str
    layer: int | None
    x: int | None
    y: int | None
    nearest_label: str = ""
    nearest_distance: float | None = None
    #: 位号里的引用后缀，如 `P1_PT100101.PV` 的 `PV`
    field: str = ""

    @property
    def base_tag(self) -> str:
        """去掉 `.PV` 之类后缀的位号主名，用于 join 点表。"""
        return self.tag.split(".")[0]


@dataclass
class PageExtract:
    page: str
    width: int | None = None
    height: int | None = None
    template: str = ""
    bindings: list[TagBinding] = field(default_factory=list)
    labels: list[str] = field(default_factory=list)


def extract_page(doc, page: str, label_radius: float | None = 200.0) -> PageExtract:
    """从一个 Document 抽出位号绑定台账。

    `label_radius` 是就近中文标签匹配的距离上限（画布像素）。
    超出即视为无关，留空字符串——宁缺毋滥，错误的标签比没有标签更有害。
    传 None 表示不限距离。
    """
    all_shapes = list(iter_shapes(doc.shapes))
    labels: list[tuple[str, tuple[int, int, int, int]]] = []
    tagged: list[tuple[str, dict, tuple | None]] = []

    for shape in all_shapes:
        box = bbox(shape)
        tag = shape_tag(shape)
        if tag:
            tagged.append((tag, shape, box))
        elif box and is_static_label(shape):
            labels.append((shape["content"], box))

    page_info = doc.page_info
    result = PageExtract(
        page=page,
        width=page_info.get("docWidth"),
        height=page_info.get("docHeight"),
        template=page_info.get("strTemplateName", ""),
        labels=[text for text, _ in labels],
    )

    for tag, shape, box in tagged:
        nearest, distance = "", None
        if box:
            cx, cy = center(box)
            for text, label_box in labels:
                lx, ly = center(label_box)
                d = math.hypot(cx - lx, cy - ly)
                if distance is None or d < distance:
                    nearest, distance = text, d
            if label_radius is not None and distance is not None and distance > label_radius:
                nearest, distance = "", None
        result.bindings.append(
            TagBinding(
                page=page,
                tag=tag,
                shape_name=shape.get("name", ""),
                layer=shape.get("layer"),
                x=box[0] if box else None,
                y=box[1] if box else None,
                nearest_label=nearest,
                nearest_distance=round(distance, 1) if distance is not None else None,
                field=tag.split(".", 1)[1] if "." in tag else "",
            )
        )
    return result


def referenced_tags(doc) -> list[str]:
    """`Tag` 流里登记的全部位号（含 `tag` 与 `ani` 两组）。

    这是页面级的位号清单，比遍历图元更全——动画绑定(`ani`)不一定挂在
    带 `strDLTag` 的图元上。
    """
    out: list[str] = []

    def walk(node):
        if isinstance(node, str):
            out.append(node)
        elif isinstance(node, dict):
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(doc.tags)
    return out
