# supcon-pic

**中控技术 SUPCON DCS** 流程图 (`.pic`) 与工程点表 (`Tags.mdb`) 解析器。

`.pic` 是 SUPCON WebField 系列 DCS 操作站流程图的私有二进制格式（内部魔数 `SDFF`），
由官方组态软件 SCDrawEx 产生。**没有公开规格，也没有其他开源实现**——本项目的
格式结论全部来自对真实工程文件的逆向，并已在 82 个文件上全量验证。

解析器只用 Python 标准库（`struct` + `zlib`）。

## 能做什么

- 解析 `.pic` 的全部五个数据流（`DocInfo` / `PageInfo` / `Shape` / `Tag` / `Text`）
- 抽取流程图上的 **DCS 位号绑定**及其屏幕坐标、图层、显示格式
- 就近匹配位号与画面上的静态中文标签
- 读取工程点表，join 出位号的**中文描述、工程量程、单位、六级报警限**

## 安装

```bash
pip install -e .            # 解析 .pic，零第三方依赖
pip install -e ".[tagdb]"   # 额外支持读 Tags.mdb 点表
```

## 用法

### 命令行

```bash
# 批量概览，同时充当解析自检
supcon-pic info /path/to/流程图目录/

# 导出单个文件的属性树 JSON（排查格式问题用）
supcon-pic dump 喷雾干燥.pic --stream Tag

# 抽取位号台账
supcon-pic tags /path/to/流程图目录/ -o tags.csv

# 台账 join 工程点表，补中文描述 / 单位 / 量程
supcon-pic tags /path/to/流程图目录/ -o tags.csv --project /path/to/SUPCON_PROJECT
```

### Python

```python
from supcon_pic import load, extract_page, referenced_tags

doc = load("喷雾干燥.pic")
doc.page_info["docWidth"]      # 1920
len(doc.shapes)                # 494
doc.texts[:4]                  # ['补水阀', '油泵', '雾化器', '冷风机']
referenced_tags(doc)[:2]       # ['P1_PT100101A01_PV', 'P1_FE100102A01_PV']

page = extract_page(doc, "喷雾干燥.pic")
page.bindings[0].tag           # 'P1_PT100101A01_PV'
page.bindings[0].nearest_label # '过滤器'
```

```python
from supcon_pic.tagdb import load_project

tags = load_project("/path/to/SUPCON_PROJECT")
tags["P1_PT100201B_3"].desc        # '出口压力'
tags["P1_PT100201B_3"].type_name   # 'AI'
tags["P1_PT100201B_3"].limits      # {'LL': ..., 'H': ..., ...}
```

> 文档与示例中的位号、描述均为**结构同形的虚构样例**（`P1_PT100101A01_PV` 之类）。
> 格式规格、解码逻辑与实测统计是真实的，具体现场数据不在本仓库内。

## 实测规模

在一个磷酸铁锂产线的 DCS 工程上：

| | |
|---|---|
| 流程图页 | 82（全部解析成功） |
| 图元 | 28,521 |
| 唯一位号 | 12,012 |
| 中文标签 | 2,297 |
| 点表位号 | 50,877（14 个控制站） |
| **流程图位号 → 点表命中率** | **98.3%**（未命中的是表达式而非位号） |

## 文档

- [docs/status.md](docs/status.md) — **项目状态、下一步与仓库约定（先看这份）**
- [docs/format-spec.md](docs/format-spec.md) — SDFF 容器与属性树的完整格式规格
- [docs/tag-database.md](docs/tag-database.md) — `Tags.mdb` 点表结构与读取
- [docs/research-notes.md](docs/research-notes.md) — 调研全记录：溯源、逆向过程、
  踩坑、工具选型、数据规模与应用价值分析

## 注意

- **仓库不收任何客户工程数据**。`.pic` / `.mdb` / `.csv` / `.zip` 已在 `.gitignore`
  中排除——这些文件含现场位号与工艺信息。
- 就近标签匹配是启发式，默认 200px 距离上限，超出留空。需要高置信度语义时
  **优先用点表的 `Tag_Desc`**，就近标签只作补充。
- **别直接用 `access_parser` 读点表**——它的 Jet4 文本解码有 bug，会毁掉 28% 的
  中文描述，其中一部分坏得"看起来很正常"。本项目已绕过，机理见
  [docs/tag-database.md §5](docs/tag-database.md)。

## 开发

```bash
pip install -e ".[dev]"
pytest
```

测试用合成的 SDFF 文件做往返验证，不依赖任何客户数据。
