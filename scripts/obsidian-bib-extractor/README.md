# Obsidian Bib Extractor（公开版）

一个面向 Obsidian 笔记库的 Python 工具集，用于从 Markdown 中提取 DOI、arXiv、PMID 和普通链接，获取文献元数据，生成去重后的 BibTeX，并支持把超链接替换为 `[@citekey]` 以及将失败链接补充导入 Zotero。

该目录是从个人工作目录整理出的可分享版本，已移除个人路径、真实 BibTeX 数据、缓存、报告和导出库数据，并补充了最小示例与环境说明。

## 功能概览

- `obsidian_bib_extractor.py`
  - 递归扫描 Markdown
  - 提取 DOI / arXiv / PMID / URL
  - 抓取元数据并生成 `BibTeX`
  - 输出结构化报告，便于人工复核
- `obsidian_cite_replacer.py`
  - 使用用户提供的 `.bib` 文件匹配超链接
  - 把链接替换成 `[@citekey]`
  - 支持 dry-run 和备份写回
- `zotero_failed_url_importer.py`
  - 读取提取报告里的失败 URL
  - 优先尝试获取元数据并导入 Zotero
  - 必要时退回为网页条目导入

## 目录结构

```text
scripts/obsidian-bib-extractor/
├── obsidian_bib_extractor.py
├── obsidian_cite_replacer.py
├── zotero_failed_url_importer.py
├── requirements.txt
├── strategy_config.json
├── strategy_fast.json
├── strategy_full.json
├── .gitignore
└── examples/
    ├── input/
    │   ├── sample_note.md
    │   └── sample_links.md
    └── output/
        ├── sample_output.bib
        └── sample_report.json
```

## 运行环境

- 操作系统：macOS / Linux / Windows 均可，只要安装 Python 3.11+
- Python：推荐 `3.11` 或 `3.12`
- 网络：抓取 DOI、arXiv、PMID、网页元数据时需要联网
- 可选依赖：若要使用 Zotero 导入功能，需要本机安装 Zotero，并启用 Zotero Connector 的本地接口

## 安装

建议使用虚拟环境：

```bash
cd /path/to/xnian-claws/scripts/obsidian-bib-extractor
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Windows PowerShell 可使用：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## 最小示例

### 1) 从 Markdown 提取 BibTeX

```bash
python obsidian_bib_extractor.py \
  --input ./examples/input \
  --output ./examples/output/demo_run.bib \
  --report ./examples/output/demo_run_report.json \
  --cache ./examples/output/demo_cache.sqlite \
  --verbose
```

### 2) 预览把超链接替换成 `[@citekey]`

```bash
python obsidian_cite_replacer.py \
  --input ./examples/input \
  --bib ./examples/output/sample_output.bib \
  --report ./examples/output/cite_replace_preview.json \
  --all-files \
  --dry-run
```

### 3) 将失败 URL 补充导入 Zotero（可选）

```bash
python zotero_failed_url_importer.py \
  --report ./examples/output/demo_run_report.json \
  --cache ./examples/output/demo_cache.sqlite \
  --target-collection-name "Imported from Obsidian" \
  --fallback-collection-name "Webpage fallback" \
  --dry-run
```

## 脚本说明

### `obsidian_bib_extractor.py`

用途：扫描 Obsidian 或普通 Markdown 目录，抽取文献标识符和链接，抓取元数据并生成 `BibTeX`。

常用参数：

- `--input <dir>`：必填，输入目录
- `--output <file>`：输出 `.bib`，默认 `references.bib`
- `--report <file>`：输出提取报告，默认 `extraction_report.json`
- `--cache <file>`：缓存文件，默认 `cache.sqlite`
- `--dry-run`：只提取候选，不发网络请求
- `--verbose`：打印详细日志
- `--exclude-dir <name>`：额外排除目录
- `--keep-arxiv-version`：保留 arXiv 版本号
- `--timeout <sec>`：请求超时
- `--max-retries <n>`：失败重试次数
- `--trust-env-proxy`：允许读取代理设置
- `--strategy-config <file>`：指定策略配置文件

### `obsidian_cite_replacer.py`

用途：用一个已有的 `.bib` 文献库匹配 Markdown 中的链接，并替换为 `[@citekey]`。

常用参数：

- `--input <dir>`：必填，输入目录
- `--bib <file>`：BibTeX 文件路径，默认 `references.bib`
- `--report <file>`：替换报告路径
- `--dry-run`：只预览，不写回
- `--all-files`：处理全部 Markdown
- `--path-contains <text>`：只处理路径中包含某段文本的文件；如不需要过滤，传 `--all-files`
- `--backup-ext <ext>`：写回前备份扩展名，例如 `.bak`

### `zotero_failed_url_importer.py`

用途：对主提取流程中失败的 URL 进行第二轮处理，并尝试导入 Zotero。

前置条件：

- 已安装 Zotero 桌面端
- 本机的 Zotero 本地 API 可访问（默认 `http://127.0.0.1:23119`）
- 目标 collection 已在 Zotero 中存在

常用参数：

- `--report <file>`：主提取报告路径，默认 `extraction_report.json`
- `--cache <file>`：缓存路径，默认 `cache.sqlite`
- `--target-collection-name <name>`：主导入 collection 名称
- `--fallback-collection-name <name>`：网页回退 collection 名称
- `--out <file>`：导入报告输出路径
- `--dry-run`：只演练，不发请求到 Zotero
- `--limit <n>`：限制处理的失败 URL 数量
- `--trust-env-proxy`：读取代理设置

## 策略配置

- `strategy_config.json`：默认策略
- `strategy_fast.json`：更保守，速度更快
- `strategy_full.json`：更偏召回，适合补全更多 URL

如需自定义，可复制其中一个配置文件后通过 `--strategy-config` 指定。

## 示例数据说明

`examples/input/` 中包含两个脱敏示例 Markdown 文件，只使用公开 DOI / arXiv / PMID / URL。

`examples/output/` 中包含：

- `sample_output.bib`：一个小型示例 BibTeX 输出
- `sample_report.json`：一个小型示例提取报告

这些文件只用于说明工具行为，不代表真实个人知识库内容。


## Skill 调用

本仓库已经附带一个可复用 skill：

- [`../../skills/obsidian-bib-extractor-workflow/SKILL.md`](../../skills/obsidian-bib-extractor-workflow/SKILL.md)

适用场景：

- 让别人的 Codex 直接调用这套工具
- 让 Claude Code 按同样的工作流执行
- 统一约束 dry-run、输出文件名和 Zotero 前置条件

快速用法：

- 对 Codex：让它读取仓库根目录下的 `skills/obsidian-bib-extractor-workflow/SKILL.md`，或把该目录复制到 `$CODEX_HOME/skills/`
- 对 Claude Code：在提示词中明确要求它先读取仓库根目录下的 `./skills/obsidian-bib-extractor-workflow/SKILL.md`
- 具体提示词模板见 [`../../skills/obsidian-bib-extractor-workflow/references/agent-invocation.md`](../../skills/obsidian-bib-extractor-workflow/references/agent-invocation.md)

## 隐私与分享建议

若将本项目上传到 Git 仓库或分享给他人，建议不要提交以下内容：

- 虚拟环境目录，如 `.venv/`
- 缓存文件，如 `*.sqlite`
- 运行报告，如 `*_report.json`
- 真实输出的 `*.bib`
- 备份文件，如 `*.bak`
- 任何包含本机绝对路径、Zotero 导出路径、PDF 存储路径的 JSON / 文本文件

本目录已通过 `.gitignore` 对这些内容做了基础屏蔽，但仍建议在分享前自行复核生成产物。

## 常见问题

- `network`：网络请求失败，检查网络或代理
- `http_429` / `http_5xx`：目标服务限流或不稳定，可稍后重试
- `no_doi_found`：目标页面中没有可识别 DOI
- `parse_error`：返回内容不是有效 BibTeX 或接口结构变化
- `paywall`：内容受权限保护，工具无法直接抓取
- Zotero 导入失败：通常与本地接口不可达、collection 名称不匹配或 Connector 未就绪有关

## 兼容性说明

- 本分享版保留原有 3 个脚本的核心能力和主要 CLI 参数
- 未包含任何真实文献库、真实缓存和历史运行结果
- 默认值尽量保持通用，不依赖私人目录结构
