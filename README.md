# MergeBid — 标书 Markdown 智能合并工具

根据 Markdown 大纲自动遍历并合并各章节 `.md` 文件，提供 **CLI 命令行**（纯 Python 标准库）与 **PySide6 图形界面** 两种模式。

## 核心功能

- **大纲驱动合并**：按大纲层级（默认 4 级或 `leaf` 末级）匹配章节文件，输出目录默认为待合并文件夹的同级目录。
- **序号/命名容错**：兼容标点空格差异、非法字符替换、文件名截断及仅序号命名（如 `2.3.1.md`）；缺失章节会保留标题并在合并后汇总提示。
- **图片路径重算**：自动将章节内的相对图片/资源路径重算为相对于最终输出文件所在目录的路径，并对断链或预写路径给出告警。
- **参数记忆复用**：自动保存运行配置，支持在界面或命令行中一键代入上次参数。

## 快速开始

### 1. 图形界面模式（PySide6）

首次使用若需安装界面依赖：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install PySide6
```

启动界面：

```bash
.venv/bin/python merge_bid.py --gui
# 或
 uv run merge_bid_gui.py
```

### 2. CLI 命令行模式

```bash
# 常规合并（默认输出到待合并文件夹的同级目录：<大纲文件名>-合并版.md）
python3 merge_bid.py -O outline.md -i chapters

# 指定输出文件夹与剔除章节首行重复标题
python3 merge_bid.py -O outline.md -i chapters -d dist --strip-duplicate-title

# 预检匹配与图片路径（不写入合并文件）
python3 merge_bid.py -O outline.md -i chapters --dry-run

# 快速代入上次运行参数（支持局部覆盖）
python3 merge_bid.py --use-last
python3 merge_bid.py --use-last --dry-run
```

## 常用 CLI 参数

| 参数 | 说明 | 默认值 |
| --- | --- | --- |
| `--gui` | 启动 PySide6 图形界面 | 关闭 |
| `--use-last` | 代入上次运行保存的参数 | 关闭 |
| `-O`, `--outline` | 大纲 Markdown 文件路径 | — |
| `-i`, `--input-dir` | 待合并章节目录（递归遍历 `.md`） | `output` |
| `-d`, `--output-dir` | 输出文件夹路径 | `input-dir` 同级目录 |
| `-o`, `--output` | 自定义输出文件路径或文件名 | `<输出目录>/<大纲名>-合并版.md` |
| `--level` | 填充层级（`1`~`6` 或 `leaf`） | `4` |
| `--missing-policy` | 缺失处理：`placeholder` / `empty` / `error` | `placeholder` |
| `--strip-duplicate-title` | 剔除章节正文首行重复标题 | 关闭 |
| `--report` | 导出 JSON 审计报告路径 | 不导出 |
| `--dry-run` | 仅预检，不写入文件 | 关闭 |

## 运行测试

```bash
# CLI 单元测试
python3 -m unittest test_merge_bid.py -v

# 全量测试（含 PySide6 GUI）
.venv/bin/python -m unittest discover -p "test_*.py" -v
```
