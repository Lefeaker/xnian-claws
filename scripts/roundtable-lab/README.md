# Roundtable Lab（公开版）

本地证据驱动的多人物圆桌工具。它把每个角色绑定到自己的材料库，先从本地文档检索证据，再进入多轮圆桌讨论，适合做读书、研究和概念辨析时的“带材料对话”。

本项目受李继刚的 [`ljg-skill-roundtable`](https://github.com/lijigang/ljg-skill-roundtable) 启发：保留主持人推进、多轮追问、`可 / 止 / 深入此节 / 引入新人物` 等交互思路；同时改造成一个可本地运行的 Python 工具，增加了独立人物材料库、向量检索、证据摘录、材料忠实度稽核和 Web UI。当前实现与原 skill 的差异见 [`docs/ljg-roundtable-gap-analysis.md`](docs/ljg-roundtable-gap-analysis.md)。

这个目录是从个人工作目录整理出的可分享版本，已移除真实 API key、本地索引、历史 session、PDF/EPUB 原始材料和材料派生索引。使用者需要自行准备有权使用的本地材料。

## 功能概览

- 按人物建立材料库：每个角色只检索自己的 `materials/人物名/sources/`
- 支持 `md`、`txt`、`org`、`pdf`、`epub`、`docx` 等材料格式
- 使用 embedding 建立本地 SQLite 向量索引
- CLI 一次性运行圆桌，也可启动本地 Web UI 多轮推进
- 每位人物发言附带依据材料、引用/化用位置、推演边界和可能越界点
- 可选稽核员检查发言是否超出材料支持
- 浏览器端保存 transcript、研究便签和分轮记录

## 目录结构

```text
scripts/roundtable-lab/
├── materials/
│   └── README.md             # 材料目录说明，真实材料不随仓库发布
├── personas/                 # 人物边界和发言约束示例
├── roundtable_lab/           # Python 实现
├── scripts/                  # CLI / Web 启动入口
├── tests/
├── web/static/               # 本地 Web UI
├── config.example.toml
├── .env.example
└── README.md
```

运行后会在本目录生成：

```text
indexes/roundtable.sqlite     # 本地 SQLite 向量索引，不要提交
sessions/                     # 每次圆桌输出，不要提交
```

## 安装

```bash
cd /path/to/xnian-claws/scripts/roundtable-lab
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

如果要解析 DOCX：

```bash
pip install -e ".[docx]"
```

## 配置

复制示例配置：

```bash
cp .env.example .env
cp config.example.toml config.toml
```

在 `.env` 中填写 API key：

```bash
ROUNDTABLE_CHAT_API_KEY=你的对话模型 API key
ROUNDTABLE_EMBED_API_KEY=你的 embedding API key
```

如果对话和 embedding 使用同一个 SiliconFlow key，也可以只填：

```bash
SILICONFLOW_API_KEY=你的 SiliconFlow API key
```

常用模型、base URL、并发和检索参数在 `config.toml` 中配置，也可以用环境变量覆盖。对话模型相关环境变量使用 `ROUNDTABLE_CHAT_*`，embedding 相关环境变量使用 `SILICONFLOW_*` 或 `ROUNDTABLE_EMBED_*`。

## 放材料

例如：

```text
materials/汪曾祺/sources/受戒.md
materials/费孝通/sources/乡土中国.pdf
materials/项飙/sources/把自己作为方法.md
```

公开仓库不附带这些材料。请只放你自己拥有使用权、或确认可合法处理的文件。

## 建索引

```bash
python scripts/ingest.py
```

如果材料有较大改动，或想清空旧索引重新生成：

```bash
python scripts/ingest.py --rebuild
```

索引器默认读取 `materials/`。如果你把材料放在别处：

```bash
python scripts/ingest.py --materials /path/to/materials
```

材料目录的一级子目录名就是人物名，必须和 `--participants` 中的名字一致。例如 `materials/费孝通/sources/乡土中国.pdf` 对应参与者 `费孝通`。

## 运行圆桌

### CLI：一次性生成一轮

```bash
python scripts/roundtable.py \
  --topic "汪曾祺笔下人物的浑圆状态，现代人相比于他们到底缺少什么" \
  --participants 汪曾祺 沈从文 费孝通 项飙 韩炳哲 庄子 \
  --audit
```

每位人物的输出都会包含：

```text
【发言】
【依据材料】
【引用/化用位置】
【推演边界】
【可能越界点】
```

`--audit` 会额外让稽核员检查“是否超出材料支持”。

常用参数：

- `--question`：指定当前轮问题；不传时默认使用 `--topic`
- `--participants`：指定参与人物；不传时使用 `personas/` 里的全部人物
- `--history`：传入已有讨论上下文，让本轮接着前文回答
- `--top-k`：每个人物检索多少个证据片段；默认读取 `config.toml` 的 `top_k`
- `--config`：指定配置文件路径
- `--root`：指定项目根目录，便于从其他目录调用

CLI 每次会在 `sessions/时间戳-主题/` 下写入一轮结果，适合批处理或在终端里快速生成材料。

安装为 editable package 后，也可以直接使用命令：

```bash
roundtable-lab-ingest --rebuild
roundtable-lab \
  --topic "自由意志是否存在？" \
  --participants 丹尼特 萨特 斯宾诺莎 \
  --audit
```

## 打开本地前端

### Web UI：多轮交互

```bash
python scripts/web.py
```

然后打开：

```text
http://127.0.0.1:8765
```

如果默认端口被占用：

```bash
python scripts/web.py --port 8766
```

如果安装了 console script：

```bash
roundtable-lab-web --port 8765
```

网页里的同一场圆桌会保留 session transcript：同一轮内人物按顺序发言，后发言者能看到前面发言；点击“继续下一轮”时，所有人物会看到前面轮次的完整记录。“新开圆桌”会清空当前浏览器 session。

阅读交互：

- 讨论现场不再强制滚到最新。只有当你本来就在底部时，才会自动跟随新发言。
- 如果你正在读旧内容，新发言不会打断阅读，页面会显示“跳到最新”按钮。
- 消息正文会渲染基础 Markdown，包括 `**粗体**`、标题、列表、行内代码和代码块。
- 右侧“研究便签”会自动保存。已有 session 时保存到该 session 的 `notes.md`；还没开始 session 时保存为浏览器本地草稿。
- 每条发言都有“摘录到便签”。如果你先选中一段文字，只摘录选中文本；否则摘录整条发言。

指令说明：

- `可`：接受当前本轮问题；第一轮问题为空时会自动进入“开场定义”。
- `深入此节`：围绕上一轮主持人提炼的核心争议继续深挖。
- `引入新人物`：把“新人物”输入框中的名字加入本场圆桌，并请其回应当前争议。
- `止`：结束讨论，生成 `knowledge-network.md`，包含全局总结、完整知识网络和开放问题。

推荐的 Web 使用流程：

1. 在 `materials/人物名/sources/` 放入每个人物的材料。
2. 运行 `python scripts/ingest.py --rebuild` 建索引。
3. 启动 `python scripts/web.py`。
4. 在浏览器里填写主题和参与者，开始第一轮。
5. 根据主持人的下一层问题输入 `可`、`深入此节`、`引入新人物` 或 `止`。
6. 在右侧便签摘录关键段落，结束后到 `sessions/` 查看完整记录。

多轮保存结构：

```text
sessions/某次圆桌/
  topic.md
  rounds.md
  transcript.md
  final.md
  round-01/
    question.md
    agents.md
    audit.md
    moderator.md
    evidence/
  round-02/
    ...
```

## 典型用法

### 读书会前做角色化材料对读

把每位作者的公开笔记、摘录或你有权处理的原文放入对应目录，建立索引后让不同作者围绕同一个问题发言。打开 `--audit` 可以快速看到哪些判断来自材料，哪些地方可能是模型发挥。

### 写作前梳理争议结构

先在 Web UI 中围绕主题跑 2-3 轮，用 `深入此节` 追问主持人指出的关键分歧。结束时输入 `止`，生成 `knowledge-network.md`，再把开放问题转成写作提纲。

### 增加新人物

1. 新建 `personas/新人物.md`，写清楚角色边界、可依据的文本范围和禁止发挥的地方。
2. 新建 `materials/新人物/sources/`，放入材料。
3. 重新运行 `python scripts/ingest.py --rebuild`。
4. CLI 中把新人物加入 `--participants`，或在 Web UI 使用 `引入新人物`。

### 只用自己的笔记，不放完整书籍

不必放 PDF/EPUB。可以只把你自己的读书笔记、摘录卡片、公开资料整理稿放进 `sources/`。这更适合开源协作，也能降低版权和隐私风险。

## 常见问题

- `Missing chat API key`：检查 `.env` 里是否填写了 `ROUNDTABLE_CHAT_API_KEY`，或是否用 `SILICONFLOW_API_KEY` 作为共用 key。
- `Missing embedding API key`：检查 `.env` 里是否填写了 `SILICONFLOW_API_KEY` 或 `ROUNDTABLE_EMBED_API_KEY`。
- 某个人物没有证据：确认 `materials/人物名/sources/` 的人物名和 `--participants` 完全一致，并重新建索引。
- PDF/EPUB 解析效果差：优先使用 Markdown/TXT 摘录稿，或把复杂材料拆成更干净的文本文件。
- Web 页面看不到历史圆桌：确认当前工作目录是 `scripts/roundtable-lab`，历史记录默认保存在该目录下的 `sessions/`。
- 输出太泛：减少参与者数量，提高材料质量，或把 `--question` 写得更具体。

## 隐私与开源边界

不要提交以下内容：

- `.env`、`config.toml` 或任何真实 API key
- `materials/*/sources/` 下的 PDF、EPUB、DOCX、Markdown 原文
- `indexes/roundtable.sqlite` 及 SQLite 派生文件
- `sessions/` 运行记录，除非已经人工确认可公开
- `.venv/`、`__pycache__/`、`.pytest_cache/`、`.DS_Store`

提交前建议运行：

```bash
git status --short
rg -n --hidden -i "api[_-]?key|secret|token|password|bearer|sk-" .
```

如果安装了专用工具，也建议用 `gitleaks` 或 `detect-secrets` 再扫一遍。

## License

本项目随 `xnian-claws` 仓库采用 MIT License。李继刚原版 `ljg-skill-roundtable` 同样采用 MIT License；本项目不是原 skill 的直接复制，而是在其圆桌方法启发下做的本地证据化实现。
