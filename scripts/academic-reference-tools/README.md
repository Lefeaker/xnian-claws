# 参考论文处理脚本

这个目录集中存放论文整理、引用抽取、BibTeX 生成、`bibkey` 回填、Zotero 补救导入相关的脚本和配置文件。

设计目标：

- 把“论文正文 / 图片资源 / 处理脚本 / 配置文件”分开管理
- 让常见流程可以重复执行，而不是每次手工处理
- 尽量让脚本对路径和个人环境解耦，便于迁移或开源

---

## 目录结构

```text
参考论文处理脚本/
├── README.md
├── requirements.txt
├── strategy_config.json
├── strategy_fast.json
├── strategy_full.json
├── convert_docx_to_obsidian.sh
├── obsidian_bib_extractor.py
├── obsidian_cite_replacer.py
├── reference_bibkey_mapper.py
├── zotero_failed_url_importer.py
└── deep_research辅助脚本/
    ├── README.md
    ├── fix_citations.py
    ├── clean_inline_citations.py
    ├── clean_reference_list.py
    └── clean_references.py
```

---

## 脚本总览

### 1. `convert_docx_to_obsidian.sh`

**用途**

- 把 `.docx` 论文转换成 Obsidian 可用的 Markdown
- 提取图片资源并整理到统一目录
- 对参考文献和部分标题结构做额外清洗

**主要处理**

- 调用 `pandoc` 将 Word 转为 Markdown
- 提取图片到 `files/<论文名>/`
- 统一图片链接路径
- 如果系统安装了 `wmf2gd`，把 `WMF` 转成 `PNG`
- 将参考文献列表中的 `[1] ...` 转成脚注 `[^1]: ...`
- 把部分锚点标题转成 Markdown 标题

**输入**

- 一个 `.docx` 文件
- 一个输出目录

**输出**

- 转换后的 `.md`
- 提取出的图片目录

**示例**

```bash
./convert_docx_to_obsidian.sh "/path/to/input.docx" "/path/to/output_dir"
```

---

### 2. `obsidian_bib_extractor.py`

**用途**

- 递归扫描 Markdown 文件
- 提取 DOI、arXiv、PMID、普通 URL 等文献线索
- 联网抓取元数据并生成去重后的 `.bib`

**适合场景**

- 论文笔记里已经有很多链接或标识符，但还没有系统 BibTeX 库
- 想先补全文献库，再做正文引用标准化

**支持的线索类型**

- DOI
- arXiv
- PMID
- 网页 URL

**输出**

- `references.bib` 或你指定的 `.bib`
- `extraction_report.json` 或你指定的报告文件
- SQLite / JSON 缓存文件

**特性**

- 自动去重
- 带缓存，减少重复抓取
- URL 反查支持多种策略
- 支持自定义 `User-Agent`

**示例**

```bash
python obsidian_bib_extractor.py \
  --input "/path/to/notes" \
  --output "/path/to/references.bib" \
  --report "/path/to/extraction_report.json"
```

如需更保守或更激进的 URL 识别策略，可以传：

```bash
--strategy-config strategy_fast.json
```

或：

```bash
--strategy-config strategy_full.json
```

---

### 3. `obsidian_cite_replacer.py`

**用途**

- 按 DOI 或 URL 与现有 `.bib` 总库匹配
- 把 Markdown 中的超链接替换成 `[@citekey]`

**可处理的链接形式**

- Markdown 链接：`[text](url)`
- 尖括号链接：`<url>`
- 裸链接：`https://...`

**适合场景**

- 已经有 `.bib` 总库
- 想把正文中的普通链接引用标准化成 Pandoc / Obsidian Citation 风格

**注意**

- 现在默认处理输入目录下的全部 Markdown
- 如果只想限制到某类路径，可手动加 `--path-contains`
- 可配合 `--dry-run` 先预览

**示例**

```bash
python obsidian_cite_replacer.py \
  --input "/path/to/obsidian-vault" \
  --bib "/path/to/library.bib" \
  --report "/path/to/cite_replace_report.json" \
  --dry-run
```

仅处理相对路径包含某个关键词的文件：

```bash
python obsidian_cite_replacer.py \
  --input "/path/to/obsidian-vault" \
  --bib "/path/to/library.bib" \
  --path-contains "Literature Review"
```

---

### 4. `reference_bibkey_mapper.py`

**用途**

- 从 Markdown 脚注参考文献、编号参考文献，或原始 `docx` 的 Word XML 参考文献列表中提取条目
- 与已有 `.bib` 总库匹配
- 把结果回填为 `[@citekey]`

**匹配方式**

- 优先用 DOI
- 其次用标题精确匹配
- 必要时用 Crossref 做辅助匹配

**输出**

- `*_with_bibkeys.md`
- `*_bibkey_mapping.json`
- `*_bibkey_mapping.txt`

**适合场景**

- 论文已经有脚注参考文献或编号参考文献
- 你想批量把它们映射到现有 BibTeX 库中的条目

**示例**

```bash
python reference_bibkey_mapper.py \
  --source-md "/path/to/thesis.md" \
  --bib "/path/to/library.bib" \
  --output-copy "/path/to/thesis_with_bibkeys.md" \
  --mapping-json "/path/to/thesis_bibkey_mapping.json" \
  --mapping-txt "/path/to/thesis_bibkey_mapping.txt"
```

如果想用原始 `docx` 的参考文献段落做辅助：

```bash
python reference_bibkey_mapper.py \
  --source-md "/path/to/thesis.md" \
  --source-docx "/path/to/thesis.docx" \
  --bib "/path/to/library.bib" \
  --output-copy "/path/to/thesis_with_bibkeys.md" \
  --mapping-json "/path/to/thesis_bibkey_mapping.json" \
  --mapping-txt "/path/to/thesis_bibkey_mapping.txt"
```

---

### 5. `zotero_failed_url_importer.py`

**用途**

- 读取文献抽取失败报告
- 把抽取失败的 URL 再尝试导入 Zotero
- 优先元数据导入，失败时回退为网页条目

**适合场景**

- 你已经运行过 `obsidian_bib_extractor.py`
- 报告里有一批 URL 没抓到 DOI / BibTeX
- 想把这些链接也尽量收编到 Zotero

**当前默认行为**

- 默认连接本机 Zotero Connector API：`http://127.0.0.1:23119`
- 默认主集合名：`Imported Articles`
- 默认回退集合名：`Webpage Fallback`
- 默认导入标签：`auto-imported`

这些值都可以通过命令行参数覆盖。

**示例**

```bash
python zotero_failed_url_importer.py \
  --report "/path/to/extraction_report.json" \
  --target-collection-name "Imported Articles" \
  --fallback-collection-name "Webpage Fallback" \
  --import-tag "auto-imported"
```

如果本机接口地址不同：

```bash
python zotero_failed_url_importer.py \
  --api-base "http://127.0.0.1:23119" \
  --report "/path/to/extraction_report.json"
```

---

### 6. `deep_research辅助脚本/`

这是一个子目录，放的是几份**面向 Deep Research 产出 Markdown 的后处理小脚本**。

它们更偏“文本结构整理”：

- 统一内联引用编号
- 重建参考文献区块
- 清理重复链接和冗余格式

它们与主目录下的 BibTeX / `bibkey` 流程是互补关系，不直接替代主流程脚本。

详见：

- `deep_research辅助脚本/README.md`

---

## 配置文件说明

### `requirements.txt`

Python 依赖列表：

- `httpx`
- `rapidfuzz`
- `bibtexparser`

### `strategy_config.json`

默认 URL 元数据反查策略。

### `strategy_fast.json`

更保守、更快，适合先快速跑一轮。

### `strategy_full.json`

更激进、覆盖更全，适合尽量提高召回率。

---

## 推荐工作流

### 场景 A：从 Word 论文开始

1. 用 `convert_docx_to_obsidian.sh` 把 `.docx` 转成 Markdown
2. 如果还没有文献库，用 `obsidian_bib_extractor.py` 抽取并生成 `.bib`
3. 如果脚注里已有参考文献，用 `reference_bibkey_mapper.py` 回填 `bibkey`
4. 如果正文里仍有普通网页链接，用 `obsidian_cite_replacer.py` 统一成 `[@citekey]`
5. 如需补救失败链接，再用 `zotero_failed_url_importer.py`

### 场景 B：已经有 Markdown 和 BibTeX 总库

1. 先用 `reference_bibkey_mapper.py` 处理脚注参考文献
2. 再用 `obsidian_cite_replacer.py` 处理正文超链接

### 场景 C：Deep Research 导出的 Markdown 很乱

1. 先在 `deep_research辅助脚本/` 里选合适的小脚本做结构清洗
2. 再决定是否进入主流程：
   - 要生成 `.bib`：用 `obsidian_bib_extractor.py`
   - 要回填 `[@citekey]`：用 `reference_bibkey_mapper.py` 或 `obsidian_cite_replacer.py`

---

## 安装依赖

系统依赖：

- `bash`
- `pandoc`
- `python3`
- `pip`
- 可选：`wmf2gd`

如果要用 Zotero 联动，还需要：

- 本地 Zotero
- Zotero Connector 本地接口可用

Python 安装示例：

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

---

## 输出文件与缓存建议

建议把运行产物输出到论文目录或工作目录，而不是直接堆在本脚本目录。

常见运行产物包括：

- `.bib`
- `.json` 报告
- `.txt` 映射结果
- `.sqlite` 缓存
- `.bak` 备份文件

这样做的好处：

- 脚本目录保持干净
- 便于版本管理
- 便于区分“脚本本体”和“针对某篇论文的运行结果”

---

## 开源与迁移说明

这个目录中的脚本已经做过一轮“去个人化默认值”整理：

- 不再依赖固定个人路径
- 默认集合名 / 标签名改为中性命名
- 默认 `User-Agent` 改为项目级标识

但仍建议在公开前再确认：

- 是否保留本地缓存文件
- 是否包含真实 `.bib` 库
- 是否包含运行生成的报告或备份文件

---

## 协作约定

- 新增论文处理脚本，优先放在这个目录
- 如果脚本依赖单独配置文件，也放在这里，并在 README 中登记
- 新增脚本至少补齐这 4 项说明：
  - 用途
  - 输入
  - 输出
  - 依赖
