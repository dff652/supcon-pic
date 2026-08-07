# 工程点表 `Tags.mdb`

流程图只存位号字符串。**中文描述、工程量程、单位和报警限全在点表里**——
这是把裸位号变成有语义的时序 measurement 的关键。

---

## 1. 位置与格式

```
SUPCON_PROJECT/<工程名>/Control/CA0/CS<NN>/Tag/Tags.mdb
```

`CS<NN>` 是控制站编号，**每站一个独立的 Tags.mdb**，位号在全工程内唯一。
实测某工程有 14 个控制站、合计 **50,877 个位号**。

格式是 Microsoft Access **Standard Jet DB**：

```
$ file Tags.mdb
Tags.mdb: Microsoft Access Database
$ head -c 20 Tags.mdb
\x00\x01\x00\x00Standard Jet DB
```

只取一个站的点表会漏掉绝大部分位号——**必须遍历所有 `*/Tag/Tags.mdb`**。

## 2. 读取工具

| 工具 | 说明 |
|---|---|
| **`access_parser`** | 纯 Python，`pip install access_parser`，无需 ODBC / Windows。**本项目采用** |
| `mdbtools` | `apt install mdbtools`，`mdb-tables` / `mdb-export`，功能等价但引入系统依赖 |

## 3. 表结构

库内共 28 张表（含 Access 自带的 `MSys*` 系统表）。业务相关的：

| 表 | 作用 | 实测行数（单站） |
|---|---|---|
| **`Tags`** | 位号主表 | 2,568 |
| `TagTypes` | 点类型定义，`Type_ID` 的权威来源 | 11 |
| **`AI`** | 模拟量输入的量程/单位/报警限，90 列 | 288 |
| `AO` | 模拟量输出，59 列 | 64 |
| `DI` | 开关量输入，51 列 | 2,048 |
| `DO` | 开关量输出，42 列 | 128 |
| `NA` / `ND` / `NN` | 中间变量 | 32 / 8 / 0 |
| `FB` | 功能块 | 0 |
| `UseRecord` | 使用记录 | 80 |

### 3.1 `Tags`（位号主表）

| 列 | 含义 |
|---|---|
| `Tag_ID` | 全局 ID |
| `Tag_Index` | 站内序号 |
| `Type_ID` | 点类型，外键到 `TagTypes` |
| `Property_ID` | **外键，指向 `AI`/`AO`/`DI`/`DO` 等类型表的同名列** |
| `Tag_Name` | 位号名，如 `P1_PT100201B_3` |
| `Tag_Desc` | **中文描述**，如 `出口压力` |
| `IsEffect` | 是否生效 |
| `CompileValue` | 编译后的二进制参数块（未解析） |

### 3.2 `TagTypes`（点类型）

库内自带，不要硬编码：

| Type_ID | Type_Name | isio | 含义 |
|---|---|---|---|
| 1 | FB | ✗ | 功能块 |
| 2 | AI | ✓ | 模拟量输入 |
| 3 | AO | ✓ | 模拟量输出 |
| 4 | DI | ✓ | 开关量输入 |
| 5 | DO | ✓ | 开关量输出 |
| 6 | NA | ✗ | 中间模拟量 |
| 7 | ND | ✗ | 中间开关量 |
| 8–11 | NN / PA / PD / PN | ✗ | 其他中间量 |

实测 `Type_ID` 分布（单站 2,568 点）：DI 2,048 / AI 288 / DO 128 / AO 64 / NA 32 / ND 8。
**开关量占大头**，纯模拟量测点只有约 11%。

### 3.3 `AI`（模拟量参数，90 列）

按 `Property_ID` join 回 `Tags`。对时序分析最有价值的列：

| 列 | 含义 |
|---|---|
| `EU` | 工程单位 |
| `SCL` / `SCH` | 量程下限 / 上限 |
| `LLL` `LL` `L` `H` `HH` `HHH` | **六级报警限** |
| `LLLDesc` … `HHHDesc` | 各级报警的中文描述 |
| `alarmlevelLLL` … `alarmlevelHHH` | 各级报警等级 |
| `ENLLL` `ENLL` `ENL` `ENH` `ENHH` `ENHHH` | 各级报警是否启用 |
| `HYS` / `HYS_OPT` | 报警死区与死区方式 |
| `TFLT` | 一阶滤波时间常数 |
| `LORLIM` / `HORLIM` | 变化率报警限 |
| `DPV` | 偏差报警 |
| `SIGNAL` / `SIGNAL_KIND` | 信号类型 |
| `SAFEVAL` / `ERRVAL` | 安全值 / 故障值 |
| `MODULE_SN` / `CHAN_SN` / `NODE_SN` | 硬件通道定位 |
| `RelateTag` | 关联位号 |

> 判读报警限时**必须同时看 `EN*` 使能位**——未启用的报警级别里仍会留着历史配置值，
> 直接把 `LL`/`HH` 当有效阈值用会引入假阈值。

## 4. 与流程图 join

流程图位号可带引用后缀，join 前先切：

```python
base_tag = tag.split(".")[0]     # P1_LS100103A01_PV.PV -> P1_LS100103A01_PV
```

实测覆盖率：

```
流程图位号 12,012 个 -> 命中点表 11,810 个 (98.3%)
```

未命中的 202 个是 `Tag.ani` 里的**表达式**而非位号
（`P1_2_M100601F_AOL OR P1_2_UF100601B_A`），真实位号覆盖率接近 100%。

## 5. 坑：`access_parser` 的 Jet4 文本解码是坏的

**直接用 `access_parser` 读，28% 的中文描述会被毁掉。** 本项目自带解码器绕过它，
但如果你打算自己写读取代码，这一节是必读的。

### 成因

Jet4 的字符串支持两种存储模式混排：

- **压缩模式**：每字符 1 字节
- **非压缩模式**：每字符 2 字节（UTF-16LE）

**`0x00` 字节是两种模式之间的切换符，不是数据。** 一条「ASCII 前缀 + 中文」的
描述典型长这样：

```
44 43 53 | 00 | 9b 4f  d9 7e  f6 65  f4 95  be 8b  9a 5b  3c 50
 D  C  S   ↑     供     给     时     间     设     定     值
        切到非压缩模式
```

`access_parser` 的 `utils.parse_type` 不认这个切换符：把整段按 UTF-8→latin1
解码，再把所有 `0x00` 统统删掉（`utils.py:191-193`）。结果：

```
正确    ->  'DCS供给时间设定值'
它给的  ->  'DCS\x00\x9bOÙ~öeô\x95¾\x8b\x9a[<P'
```

更糟的是纯 ASCII 段也会被殃及——`CV01光电` 的存储是
`43 00 56 00 30 00 31 00 | 49 51 35 75`，NUL 被删后变成 `CV01IQ5u`，
**看起来像一个正常字符串，不会被任何乱码检测发现**。

### 为什么必须在解码层修

NUL 一旦删掉，位置信息就没了，无法从结果串反推原文。
先前尝试过的「事后按 UTF-16 回编重解」的思路是错的——对
`CV01IQ5u` 这种已经丢了 NUL 的串根本无解。

### 本项目的做法

`tagdb.decode_jet4_text()` 实现了正确的切换符逻辑，
`tagdb._patched_text_decoding()` 在读库期间把它挂到 `access_parser` 的解码点上，
读完还原。实测：

```
修复前可疑行 14,385 / 50,877 (28.27%)
修复后            0 / 50,877
```

行为由 `tests/test_tagdb.py` 钉住。

> 如果改用 `mdbtools`，它的 `mdb_unicode2ascii` 本身就正确实现了切换符逻辑，
> 不会踩这个坑。
