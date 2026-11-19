# 标书合并脚本使用说明

本说明对应合并脚本 [code/merge_bid.py](code/merge_bid.py)，使用 `uv run` 直接运行（仅依赖 Python 标准库，无需额外安装依赖）。

## 当前大纲合并命令

以当前大纲 [投标大纲-企业管理制度重构版-v03.md](投标大纲-企业管理制度重构版-v03.md) 与 `output/` 目录为例：

```bash
# 1. 预检匹配情况（推荐先执行：不生成合并文件，检查缺失、重复及容错匹配提示）
uv run code/merge_bid.py --outline 投标大纲-企业管理制度重构版-v03.md --input-dir output --dry-run

# 2. 正式合并（默认模式：若存在缺失章节会在文内插入占位注释，并在合并完成后列出缺失章节提示）
uv run code/merge_bid.py --outline 投标大纲-企业管理制度重构版-v03.md --input-dir output

# 3. 严格合并（存在任何缺失章节时直接报错退出，默认输出 投标大纲-企业管理制度重构版-v03-合并版.md）
uv run code/merge_bid.py --outline 投标大纲-企业管理制度重构版-v03.md --input-dir output --missing-policy error

# 4. 指定输出文件名并导出匹配审计报告（JSON）
uv run code/merge_bid.py \
  --outline 投标大纲-企业管理制度重构版-v03.md \
  --input-dir output \
  --output 投标大纲-企业管理制度重构版-v03-合并版.md \
  --report code/merge_report.json
```

## 常用参数说明

| 参数 | 说明 | 默认值 |
| --- | --- | --- |
| `-O`, `--outline` | 投标大纲 Markdown 文件路径（必填） | — |
| `-i`, `--input-dir` | 章节 Markdown 所在目录（递归扫描 `.md`） | `output` |
| `-o`, `--output` | 合并后输出的 Markdown 文件路径 | `<大纲文件名>-合并版.md` |
| `--level` | 填充正文的大纲层级（`1`~`6` 或 `leaf` 自动识别末级标题） | `4` |
| `--missing-policy` | 缺失章节处理：`placeholder`（注释占位）/ `empty`（留空）/ `error`（报错退出） | `placeholder` |
| `--min-similarity` | 跨编号模糊匹配的最低相似度阈值（`0~1`） | `0.72` |
| `--min-code-only-similarity` | 仅编号一致时兜底匹配的最低标题相似度（`0~1`） | `0.20` |
| `--strip-duplicate-title` | 若章节文件首行重复了当前大纲标题，则自动剔除 | 关闭 |
| `--report` | 输出 JSON 格式匹配审计报告的路径 | 不输出 |
| `--dry-run` | 仅检查匹配情况与输出统计，不写入文件 | 关闭 |

## 运行单元测试

```bash
uv run python -m unittest discover -s code -v
```
