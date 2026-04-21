# xnian-claws

一个公开整理我自用工具的仓库，集中收纳可复用的 `skills`、自动化脚本和小型命令行工具。

当前先收录一个已经净化过的 Obsidian 文献处理工具，后续可以继续往 `scripts/` 和 `skills/` 里追加新项目。

## 目录结构

```text
xnian-claws/
├── scripts/
│   └── obsidian-bib-extractor/
├── skills/
│   └── obsidian-bib-extractor-workflow/
├── .gitignore
├── LICENSE
└── README.md
```

## 当前收录

- `scripts/obsidian-bib-extractor/`
  - 从 Markdown / Obsidian 笔记中提取 DOI、arXiv、PMID、URL
  - 生成去重后的 BibTeX
  - 预览或执行超链接到 `[@citekey]` 的替换
  - 将失败 URL 补充导入 Zotero
- `skills/obsidian-bib-extractor-workflow/`
  - 面向 Codex / Claude Code / 其他 agent 的工作流 skill
  - 统一约束 dry-run、输出文件和 Zotero 前置条件

## 使用方式

### 运行脚本

```bash
cd scripts/obsidian-bib-extractor
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

具体命令见 `scripts/obsidian-bib-extractor/README.md`。

### 复用 skill

如果要把 skill 安装到本地 Codex 环境：

```bash
mkdir -p "$CODEX_HOME/skills"
cp -R ./skills/obsidian-bib-extractor-workflow "$CODEX_HOME/skills/"
```

也可以直接让 agent 读取仓库里的 `skills/obsidian-bib-extractor-workflow/SKILL.md`。

## 维护约定

- `scripts/`：放可运行工具，尽量做到自描述、可独立安装
- `skills/`：放可复用 skill，优先引用仓库内现成脚本
- 提交前检查是否包含缓存、虚拟环境、绝对路径、API key 或个人数据

## License

默认采用 MIT License。
