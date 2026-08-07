"""命令行入口：`python -m sdff <命令>`。"""

from __future__ import annotations

import argparse
import csv
import glob
import json
import os
import sys

from .container import Array, load
from .shapes import extract_page, referenced_tags


def _pic_files(target: str) -> list[str]:
    if os.path.isdir(target):
        return sorted(glob.glob(os.path.join(target, "**", "*.pic"), recursive=True))
    return [target]


def _rel(path: str, root: str) -> str:
    return os.path.relpath(path, root) if os.path.isdir(root) else os.path.basename(path)


def cmd_info(args) -> int:
    """逐文件打印概览，同时充当批量解析自检。"""
    files = _pic_files(args.target)
    failed = 0
    for path in files:
        try:
            doc = load(path)
        except Exception as exc:  # noqa: BLE001 - 自检要看清哪个文件坏
            failed += 1
            print(f"FAIL {_rel(path, args.target)}: {type(exc).__name__}: {exc}")
            continue
        info = doc.page_info
        print(
            f"{_rel(path, args.target)}\t"
            f"{info.get('docWidth')}x{info.get('docHeight')}\t"
            f"shapes={len(doc.shapes)}\t"
            f"tags={len(referenced_tags(doc))}\t"
            f"texts={len(doc.texts)}\t"
            f"template={info.get('strTemplateName', '')}"
        )
    print(f"\n{len(files) - failed}/{len(files)} 解析成功", file=sys.stderr)
    return 1 if failed else 0


def cmd_dump(args) -> int:
    """把一个 .pic 的属性树导成 JSON，用于人工核对与格式排查。"""
    doc = load(args.target)

    def default(obj):
        if isinstance(obj, Array):
            return {"__array__": len(obj), "flag": obj.flag, "hex": obj.data[:32].hex()}
        return str(obj)

    payload = doc.streams if args.stream is None else {args.stream: doc.streams[args.stream]}
    json.dump(payload, sys.stdout, ensure_ascii=False, indent=2, default=default)
    print()
    return 0


def cmd_tags(args) -> int:
    """批量抽取位号台账 CSV，可选 join 工程点表补中文描述与量程。"""
    tagdb = {}
    if args.project:
        from .tagdb import load_project

        tagdb = load_project(args.project)
        print(f"点表载入 {len(tagdb)} 个位号", file=sys.stderr)

    rows = []
    for path in _pic_files(args.target):
        doc = load(path)
        page = extract_page(doc, _rel(path, args.target), label_radius=args.label_radius)
        for binding in page.bindings:
            row = {
                "page": binding.page,
                "tag": binding.tag,
                "base_tag": binding.base_tag,
                "field": binding.field,
                "shape": binding.shape_name,
                "layer": binding.layer,
                "x": binding.x,
                "y": binding.y,
                "nearest_label": binding.nearest_label,
                "nearest_distance": binding.nearest_distance,
            }
            info = tagdb.get(binding.base_tag)
            if tagdb:
                row.update(
                    desc=info.desc if info else "",
                    tag_type=info.type_name if info else "",
                    unit=info.unit if info else "",
                    range_low=info.range_low if info else "",
                    range_high=info.range_high if info else "",
                )
            rows.append(row)

    if not rows:
        print("没有找到任何位号绑定", file=sys.stderr)
        return 1
    with open(args.out, "w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    matched = sum(1 for row in rows if row.get("desc"))
    print(f"{len(rows)} 条位号绑定 -> {args.out}", file=sys.stderr)
    if tagdb:
        print(f"命中点表 {matched} 条 ({matched / len(rows) * 100:.1f}%)", file=sys.stderr)
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="sdff", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_info = sub.add_parser("info", help="打印概览 / 批量解析自检")
    p_info.add_argument("target", help=".pic 文件或目录")
    p_info.set_defaults(func=cmd_info)

    p_dump = sub.add_parser("dump", help="导出属性树 JSON")
    p_dump.add_argument("target", help=".pic 文件")
    p_dump.add_argument("--stream", choices=["DocInfo", "PageInfo", "Shape", "Tag", "Text"])
    p_dump.set_defaults(func=cmd_dump)

    p_tags = sub.add_parser("tags", help="抽取位号台账 CSV")
    p_tags.add_argument("target", help=".pic 文件或目录")
    p_tags.add_argument("-o", "--out", default="tags.csv")
    p_tags.add_argument("--project", help="解压后的 SUPCON_PROJECT 目录，用于 join 点表")
    p_tags.add_argument(
        "--label-radius",
        type=float,
        default=200.0,
        help="就近中文标签匹配的距离上限（画布像素，默认 200）",
    )
    p_tags.set_defaults(func=cmd_tags)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
