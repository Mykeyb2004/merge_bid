# `merge_bid.py` 合并时相对资源路径重算修复交接文档

## 1. 背景与问题现象

在使用 `md2docx` 将合并后的标书 Markdown（位于项目根目录）转换为 `.docx` 时，发现部分原本写在子目录章节（`output/*.md`）中的中文路径图片无法在合并稿中解析，导致转出 Word 时出现 `[Missing image: ...]` 或图片丢失。

### 复现样例与现场事实

- **单章源文件**：`output/2.3.1 项目年度总体实施计划与阶段交付框架.md`（L53、L55）
  - 写作路径：`../pics/2.3.1_年度计划图_待确认/01_年度实施进度_核查与互助服务.png`、`02_年度实施进度_培训宣传与验收移交.png`
  - **单独转换该单章**：`md2docx` 可正常解析并嵌入 2 张图片（在 `output/` 下 `../pics/...` 指向正确）。
- **合并后总稿**：`投标大纲-企业管理制度重构版-v03-合并版.md`（位于项目根目录，比 `output/` 高一层）
  - 合并结果仍原样保留 `../pics/2.3.1_年度计划图_待确认/...`
  - 在项目根目录下，`../pics/...` 会指向项目目录的上一级（不存在），导致图片断链。
- **同时存在的另一类历史写法**：`output/` 下另外 8 个含图章节（`2.2.6`、`2.2.11`、`3.1.4`、`3.2.2`、`3.3.4`、`3.4.5`、`3.5.6`、`5.1.2`）直接写了 `pics/01_...png` ～ `pics/08_...png`（即按合并后根目录视角预写的路径）。它们在合并稿里正常，但单独从 `output/` 转换或预览时会断链。

---

## 2. 根因定位

查看 `code/merge_bid.py`（纯 Python 标准库实现，`dependencies = []`）：

- `merge_document`（约 L407–L432）在拼接章节正文时：
  ```python
  chapter_path = input_dir / match.file_path
  raw_body = chapter_path.read_text(encoding="utf-8-sig")
  body = clean_chapter_body(raw_body, node, strip_duplicate_title)
  if body:
      chunks.append(body)
  ```
- 脚本直接原样拼接 `body`，**没有感知 `chapter_path.parent` 与 `output_path.parent` 之间的目录层级变化**，未对正文中的相对图片/附件链接做路径重算（rebase）。

---

## 3. 目标与修复范围

- **目标**：在 `merge_bid.py` 合并章节时，自动将源章节内的相对图片/资源路径按 `chapter_path.parent -> output_path.resolve().parent` 重算为相对于最终合并文件的 POSIX 路径；同时对异常路径给出清晰告警与审计记录。
- **涉及文件**：
  - `merge_bid.py`（保持零第三方依赖，仅使用标准库 `os.path`、`re`、`urllib.parse`、`pathlib`、`dataclasses`）
  - `test_merge_bid.py`（补充自动化单元测试）

---

## 4. 修复方案设计

### 4.1 重算范围与正则匹配边界

1. **跳过围栏代码块**：复用 `merge_bid.py` 已有的 `FENCE_RE` 状态机按行跟踪 ```` ``` ```` / `~~~`，避免修改代码块中的示例 Markdown 或 HTML。
2. **跳过行内代码**：如 `` `![示例](../pics/a.png)` `` 不应被改写。
3. **支持两类常见语法**：
   - Markdown 图片/链接（优先确保图片 `![alt](...)`；如需要也可通过参数或统一处理普通相对文件链接 `[text](...)`，注意排除纯锚点 `#...`）：
     - 标准写法：`![alt](../pics/2.3.1_年度计划图_待确认/01.png)`
     - 带可选 title：`![alt](../pics/图.png "说明")`
     - 尖括号包裹含空格路径：`![alt](<../pics/中文 目录/图 1.png>)`
     - 带嵌套括号的文件名：需正确处理成对括号或 URL 编码情况
   - HTML `<img>` 标签：`<img src="../pics/图.png" ...>`

### 4.2 路径解析与改写优先级（关键）

对每条匹配到的 `raw_url`，按以下顺序处理：

1. **直接透传（不改写）**：
   - 空字符串
   - URL scheme：`http://`、`https://`、`data:`、`mailto:` 等（注意区分 Windows 盘符如 `C:\`，不过此处是本地 Markdown 相对路径）
   - 页内锚点：`#...`
   - 绝对路径：以 `/` 开头（如 `/Users/...`）或 `Path(unquote(url)).is_absolute()`

2. **路径解码与基准查找**：
   - 对 `url` 做 `urllib.parse.unquote` 得到本地文件系统相对路径 `decoded_rel`（兼容 `%20`、`%E5%B9%B4...` 等写法）。
   - 计算两个候选真实路径：
     - `from_chapter = (chapter_path.parent / decoded_rel).resolve()`
     - `from_output = (output_dir / decoded_rel).resolve()`（其中 `output_dir = output_path.resolve().parent`）

3. **分三种情况决策**：
   - **情况 A（规范相对路径，`from_chapter.exists()` 为 True）**：
     - 使用 `os.path.relpath(from_chapter, start=output_dir)` 计算新相对路径，并转为 POSIX 分隔符（`Path(...).as_posix()`）。
     - 示例：`output/2.3.1 ...md` 中的 `../pics/2.3.1_年度计划图_待确认/01.png` → 重算为 `pics/2.3.1_年度计划图_待确认/01.png`。
     - 若原 URL 原本未用 `<>` 包裹且新路径含空格，可对空格编码为 `%20` 或用 `<>` 包裹；含中文字符建议保持直接可读的中文相对路径（`md2docx` 与常见 Markdown 编辑器均支持）。
     - 若原 URL 处于不同层级嵌套子目录（如 `output/sub/a.md` 写 `../../pics/a.png`），`os.path.relpath` 同样能自动算准。
   - **情况 B（历史预写根目录路径，`not from_chapter.exists()` 但 `from_output.exists()` 为 True）**：
     - 兼容本项目另外 8 个在 `output/` 下直接写 `pics/01_...` 的文件：保留原路径不改写，使合并稿继续可用。
     - **记录一条告警/提示**（如 `pre_rebased_for_output`），提示该章节在单独预览/转换时相对路径与所在目录不一致，便于后续统一规范。
   - **情况 C（两边均不存在）**：
     - 保留原路径不变，**记录断链告警**（含章节相对路径、原图片路径），在合并结束时打印到 `stderr` / 控制台，并写入 `--report` JSON。

### 4.3 接口与报告扩展建议

1. **`merge_document` 函数签名扩展**：
   - 新增参数 `output_dir: Path`（由 `main()` 传入 `output_path.resolve().parent`）。
   - 注意：`merge_bid.py` L509 当前默认输出为 `Path(f"{outline_path.stem}-合并版.md")`，它是相对当前工作目录（`cwd`）的；传入 `output_path.resolve().parent` 可保证无论用户在哪个目录执行脚本、是否显式传 `--output`，`output_dir` 都是实际写入目录。
2. **新增纯函数 `rebase_chapter_links(...)`（或 `rebase_markdown_asset_paths(...)`）**：
   - 输入：`text: str`, `chapter_dir: Path`, `output_dir: Path`, `chapter_rel_path: str`
   - 输出：`(rewritten_text: str, asset_warnings: list[...])`
3. **`--report` JSON 报告兼容扩展**：
   - 在现有 `summary` 与顶层字段基础上新增可选字段（如 `asset_warnings` / `rebased_image_count`），不破坏原有字段结构。
4. **CLI 汇总输出**：
   - 若有图片路径重算数量，可在摘要中打印一句统计（例如 `图片/资源路径重算: N 处`）。
   - 若有断链或目录基准不一致告警，在合并完成前/后集中输出，避免静默漏图。

---

## 5. 需要补充的单元测试（`test_merge_bid.py`）

建议至少覆盖以下 6 个场景：

1. **子目录单章合并到上级目录（核心场景）**：
   - `chapters/2.3.1.md` 内引用 `../pics/子目录/图1.png`（含中文文件名与目录名），合并到 `root/merged.md` 后自动变为 `pics/子目录/图1.png`。
2. **多层嵌套子目录**：
   - `chapters/sub/nested/a.md` 引用 `../../../pics/a.png`，合并到 `root/merged.md` 后变为 `pics/a.png`。
3. **带 title、带空格尖括号、URL 编码路径及 HTML `<img>`**：
   - `![alt](../pics/a.png "标题")`、`![alt](<../pics/中文 1.png>)`、`![alt](../pics/%E4%B8%AD%E6%96%87.png)`、`<img src="../pics/b.png" width="100" />`。
4. **代码块内的图片语法不被误改**：
   - ```` ```markdown ```` 围栏内与行内反引号 `` `![x](../pics/x.png)` `` 保持原样。
5. **外部链接与锚点不被误改**：
   - `https://...`、`http://...`、`data:image/png;base64,...`、`#section`、绝对路径保持原样。
6. **兼容根目录预写路径与断链告警**：
   - `chapters/b.md` 写 `pics/exist.png`（存在于 `root/pics/exist.png`）时保留不破坏并记录提示；引用不存在图片 `../pics/missing.png` 时保留原文本并输出告警。

---

## 6. 验收命令

在原始库（或本地测试目录）完成修改后，按以下方式验收：

1. **运行单测**：
   ```bash
   python3 -m unittest discover -s code -p "test_*.py" -v
   ```
2. **对当前项目做真实回归测试**：
   ```bash
   python3 code/merge_bid.py \
     -O "投标大纲-企业管理制度重构版-v03.md" \
     -i output \
     -o "投标大纲-企业管理制度重构版-v03-合并版.md" \
     --strip-duplicate-title \
     --report code/merge_report.json
   ```
3. **核对合并结果**：
   - 检查合并稿中原 `../pics/2.3.1_年度计划图_待确认/...` 是否已正确改写为 `pics/2.3.1_年度计划图_待确认/...`。
   - 用 `md2docx` 将新生成的合并稿转为 `.docx`，确认所有图片均正常嵌入、无 `[Missing image: ...]`。
