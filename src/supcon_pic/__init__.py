"""supcon-pic — SUPCON DCS 流程图 (`.pic`) 与工程点表解析器。

    >>> from supcon_pic import load
    >>> doc = load("喷雾干燥.pic")
    >>> doc.page_info["docWidth"], len(doc.shapes)
    (1920, 494)

格式规格见 docs/format-spec.md，逆向过程与结论见 docs/research-notes.md。
"""

from .sdff import Array, Document, SdffError, load, loads, parse_stream, read_raw_streams
from .shapes import (
    PageExtract,
    TagBinding,
    bbox,
    extract_page,
    iter_shapes,
    referenced_tags,
    shape_tag,
)

__version__ = "0.1.0"

__all__ = [
    "Array",
    "Document",
    "PageExtract",
    "SdffError",
    "TagBinding",
    "bbox",
    "extract_page",
    "iter_shapes",
    "load",
    "loads",
    "parse_stream",
    "read_raw_streams",
    "referenced_tags",
    "shape_tag",
]
