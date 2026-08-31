# repo-analyzer-skill

[English](README.md) | 中文

**它是什么：** 一个 Agent Skill，把任意 GitHub 仓库（或本地克隆）转化为结构化、基于证据的分析报告 —— 架构、模块关系、入口、执行流、风险、贡献机会 —— 每条断言都携带文件路径引用，报告发布前会被机械校验。

---

## 为什么做这个

读陌生代码库又慢又容易出错：你猜哪些文件重要，读错一堆，最后得到的理解根本不敢信。通用 LLM 摘要更糟——它自信地编造出仓库里根本不存在的 API、路径和数字。

这个项目要让代码库理解变得**快、可考证、可审计**：

- **快** —— 确定性提取和预算内代码采样几秒完成；LLM 只对精选上下文做推理，从不看整个仓库。
- **可考证** —— LLM 绝不猜测脚本能确定的事实（语言占比、依赖版本、文件数）。每条断言必须引用真实存在的文件路径。
- **可审计** —— 13 节报告 + 自动化证据校验（`verify-evidence`）+ 六指标评估框架（`eval`）。验证不了的断言进 `unknowns`，绝不进报告。

## 安装

```bash
git clone https://github.com/<you>/repo-analyzer-skill
cd repo-analyzer-skill
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"                              # 零运行时依赖；pytest 仅用于开发
```

## 使用

### 配置

```bash
export GITHUB_TOKEN=...      # 可选但强烈建议（60 -> 5000 次/小时）
export LLM_BASE_URL=...      # 任意 OpenAI 兼容端点
export LLM_API_KEY=...       # analyze / eval --judge 需要
export LLM_MODEL=...
```

同样的键也可写入 `.env`（已 gitignore）。完整列表见 [.env.example](.env.example)。

### 命令

```bash
repo-analyzer extract <url|path>                  # 确定性事实 -> repo_facts.json
repo-analyzer sample-code <url|path> --budget 40000
repo-analyzer analyze <url|path>                  # 完整管线 -> report.md + report.json
repo-analyzer validate-report output/repos/.../report.json
repo-analyzer verify-evidence output/repos/.../report.json
repo-analyzer eval --judge                        # 对照 gold cases 打分
```

本地路径不需要 token、不需要网络：`repo-analyzer extract /path/to/repo`。

### 作为 Agent Skill 使用

把 `SKILL.md` + `skill/` + `schemas/` 复制（或软链）进你的 agent 的 skills 目录：

```bash
mkdir -p ~/.claude/skills/repo-analyzer           # Claude Code
cp -r SKILL.md skill schemas docs evals ~/.claude/skills/repo-analyzer/
```

agent 随后自行解析输入、跑确定性 CLI 阶段、按四个 prompt section 对事实 + 采样代码推理、校验 13-key JSON（修复循环）、验证每条引用——**不需要 `LLM_API_KEY`**，因为推理者就是 agent 自己。Codex（`~/.codex/skills/`）等兼容 SKILL.md 的 agent 同理。

## 演示

两个真实输出，各对应一种输入模式 —— 每个都给出可复现的命令。

### Demo 1: 本地模式（零 GitHub API、零 token）

在仓库根目录运行即可复现——与 URL 模式是同一套管线，只是输入换成本地路径：

```bash
repo-analyzer analyze .
```

第一步——确定性事实提取（analyze 内部自动执行，无需 LLM key；输出逐行一致，HEAD hash 会随提交前进而变化）：

    Extracted facts: output\repos\local\repo-analyzer-skill-cef3623c\repo_facts.json
      repo:        local/repo-analyzer-skill (main @ 112d59bb60)
      languages:   Python, JSON, Markdown, TOML
      files:       95 (tree truncated: False)
      manifests:   1
      entrypoints: 1 candidates
      deps:        0 direct
      warnings:    1
        - local mode: metadata is minimal (no stars/issues); language shares are extension-based approximations

第二步——完整 13 节报告（真实产出，`output/repos/local/repo-analyzer-skill-cef3623c/report.md`，deepseek-v4-flash，31/32 条引用验证通过——未通过的那 1 条被明确标记而非掩盖——9 个 unknowns）：

> **Summary:** repo-analyzer-skill 是一个 Agent Skill（同时打包为 CLI），把任意 GitHub 仓库或本地克隆转化为结构化、基于证据的分析报告，覆盖架构、模块关系、入口、执行流、风险与贡献机会，每条断言都携带文件路径引用，发布前被机械校验。
> Evidence: `README.md` `SKILL.md` `docs/ARCHITECTURE.md` `pyproject.toml`

| Category | Technology | Role |
|---|---|---|
| language | Python | 整个运行时都是 Python，要求 >=3.11；语言占比 52.5%（274,879 字节）。[`pyproject.toml`] |
| tooling | Python stdlib (urllib, tomllib, dataclasses, argparse, json) | 刻意选择的零运行时依赖栈：urllib 调 GitHub API、tomllib 解析 TOML、dataclasses 定义事实/报告契约、argparse 建 CLI。[`pyproject.toml`] [`src/repo_analyzer/extract/dependencies.py`] [`src/repo_analyzer/cli.py`] |

### Demo 2: URL 模式（完整 GitHub API 管线）

复现命令（确定性部分不需要 LLM key；完整报告需要）：

```bash
repo-analyzer extract https://github.com/pallets/flask
repo-analyzer analyze https://github.com/pallets/flask
```

以下摘录来自一次真实 `analyze` 运行（pallets/flask @ main `d318b68347`，deepseek-v4-flash，23/23 条引用全部验证通过；完整报告见 `examples/reports/pallets-flask/report.md`）：

> **Summary:** Flask 是一个轻量级 WSGI Web 应用框架，构建于 Werkzeug（WSGI/路由）与 Jinja2（模板）之上，是开发者 import 来构建 Web 应用的核心库包（version 3.2.0.dev）。
>
> **Purpose:** 开发者通过创建 Flask app 对象、注册路由/视图函数、使用蓝图组织模块、处理请求/响应、渲染模板和静态文件来构建 Web 应用。它同时作为库 API 和 CLI 工具（'flask' 命令）用于运行开发服务器。
> Evidence: `README.md` `pyproject.toml` `src/flask/app.py` `src/flask/cli.py`

| Category | Technology | Role |
|---|---|---|
| framework | Werkzeug | 提供 WSGI 工具、路由（Map, Rule, MapAdapter）、HTTP 异常和 Flask 请求/响应周期使用的开发服务器（werkzeug.serving.run_simple）。[`src/flask/app.py`] [`src/flask/sansio/app.py`] [`pyproject.toml`] |
| framework | Click | CLI 框架；'flask' console script 注册为 flask.cli:main，FlaskGroup/AppGroup 继承 click.Group 构建 CLI 命令树。[`pyproject.toml`] [`src/flask/cli.py`] |

## 架构

```
仓库 URL / 本地路径
      │
      ▼
┌───────────── 确定性层（纯代码，零 LLM）──────────────┐
│ metadata → tree → languages → manifests → deps →    │
│ entrypoints(启发式) → git stats → file stats → readme│
│                    │                                 │
│                    ▼                                 │
│         repo_facts.json  （事实基座，schema v1）      │
│                    │                                 │
│         code_sampler（token 预算，采样清单）          │
└────────────────────┬─────────────────────────────────┘
                     ▼
        ┌────── LLM 推理层 ──────┐
        │ architecture.md  code-flow.md   │
        │ risk-analysis.md contribution.md│
        │   13-key JSON，schema 校验（修复循环）        │
        └────────────────┬────────────────┘
                         ▼
        report.json + report.md  （每条断言引用路径）
                         ▼
        verify-evidence：对照真实 tree 校验引用
```

**边界是核心设计。** `repo_facts.json` 是确定性层与下游所有环节（prompt、报告、评估）之间的唯一契约，LLM 绝不重新推导其中的数字。边界之上全是机械逻辑、有单元测试；边界之下是对有界、可审计上下文的推理。

## 工作原理

Skill 驱动一个 9 步工作流（[SKILL.md](SKILL.md) 是给 agent 看的规范；同一管线以 `repo-analyzer` CLI 暴露）：

1. **解析输入** — GitHub URL（支持 `.git` 后缀、tree/blob URL）或本地目录。
2. **提取事实** — metadata、目录树（含截断标记）、语言、清单、依赖、入口候选（每个都带产生它的启发式规则）、git 统计、文件统计、README 摘录。`repo-analyzer extract <url|path>`。
3. **读 facts digest** — 事实基座是唯一真值，其中的数字永不重算。
4. **预算内采样代码** — 入口（50% 上限）→ 清单（25% 上限）→ 最大文件（排除 tests/、二进制/lockfile 过滤），逐文件 token 估算。`repo-analyzer sample-code`。
5. **分节推理** — 四个 prompt 资产（`skill/prompts/`）：架构、代码流/入口、风险、贡献。LLM 只看到事实摘要 + 采样代码。
6. **组装并校验** — 严格按 schema（`schemas/analysis_report.schema.json`，唯一真源）输出 13 个顶层键。schema 违规触发**修复循环**：把违规回送给 LLM 自行修正，再校验一遍。
7. **校验证据** — 每条引用的路径对照真实提取 tree 检查。`repo-analyzer verify-evidence`；未通过的引用被修复或移入 `unknowns`。
8. **渲染** — `report.md` 含全部 13 节；`unknowns` 明确写出哪些无法确定、为什么。
9. **自查** — 数字与事实基座一致、每条断言有直接证据、无编造。

## 特性

- **13 节报告** — overview、tech stack、structure、architecture、core modules、entry points、execution flow、key files、dependencies、risks、reading order、contribution opportunities、unknowns。
- **Evidence-first** — 每条断言带文件路径引用；`verify-evidence` 报告 grounding 比率（flask 样本 23/23 = 0% 幻觉）。
- **双输入模式** — GitHub API（限流感知、类型化错误）或本地目录（git 快照或文件系统扫描，零网络）。
- **预算化上下文** — LLM 从不见整个仓库；采样确定性、逐文件可审计。
- **LLM 无关** — 任意 OpenAI 兼容端点（`LLM_BASE_URL` + `LLM_API_KEY`）；支持推理模型（`LLM_REASONING_EFFORT`、`LLM_MAX_OUTPUT_TOKENS`）。
- **诚实降级** — metadata 失败是硬错误；其余降级为警告 + 默认值，绝不沉默。限流时透出 `Retry-After`，不做盲重试。
- **零依赖** — Python 3.11+ 仅标准库（TOML 用 `tomllib`、JSON、urllib、subprocess）。
- **六个 CLI 子命令** — `extract`、`analyze`、`sample-code`、`validate-report`、`verify-evidence`、`eval`。

## 设计决策

| 决策 | 为什么 |
|---|---|
| **确定性层拥有所有数字** | 语言占比、依赖版本、提交数是事实而非观点。LLM 幻觉被限制在推理范围内，那里有证据校验兜底。 |
| **每条断言引用一个路径** | 没有证据的断言就是幻觉风险——它进 `unknowns` 而不是报告。证据必须*直接*（该路径本身支撑该断言）。 |
| **仅标准库** | 零供应链、可离线、秒装；3.11+ 自带 TOML（tomllib）和 HTTP（urllib）。 |
| **schema 是唯一真源** | `schemas/analysis_report.schema.json` 从 `schema.py` 导出——一个文件驱动校验、prompt 与评估；迷你 JSON-schema 校验子集保持零依赖。 |
| **预算封顶采样** | 入口配得上半个预算（核心文件比广度值钱）；超过单文件上限的文件直接跳过而非截断。 |
| **修复循环胜过 prompt 唠叨** | schema 违规是工程问题——回送给 LLM 修正、再校验、然后断言。 |
| **本地模式镜像远程语义** | git 仓库从 `ls-tree` 分析（真实 HEAD 快照，size/sha 与 API 一致）；非 git 目录降级为文件系统扫描并显式警告。 |
| **本地 ref 用哈希工作目录** | `G:\a\proj` 和 `G:\b\proj` 不能互相覆盖产物。 |
| **诚实的 unknown** | stars/issues/PR 本地不可得——保持 0/None 并标记，绝不猜测。 |

## 评估

对照人工标注的 gold cases 跑六项指标（`repo-analyzer eval`，见 [evals/results/baseline.md](evals/results/baseline.md)）：

| Case | 类型 | Structure | Entrypoint P/R/F1 | Grounding | 幻觉 | Judge (c/g/c/a, useful) |
|---|---|---|---|---|---|---|
| charmbracelet/gum | 小型 Go CLI | 8/8 (100%) | 1.00 / 1.00 / **1.00** | 18/18 | **0%** | 5/5/5/5, 5 |
| pallets/flask | 中型 Python 框架 | 10/10 (100%) | 0.50 / 1.00 / **0.67** | 16/16 | **0%** | 5/5/5/5, 5 |
| pallets/flask, 收紧前 (A/B) | 中型 Python 框架 | 10/10 (100%) | 0.50 / 1.00 / **0.67** | 23/23 | **0%** | 5/3/4.5/5, 4 |
| pallets/click | 纯 Python 库 | 10/10 (100%) | 1.00 / 1.00 / **1.00** | 15/15 | **0%** | 5/4/5/5, 5 |
| sharkdp/fd | 小型 Rust CLI | 9/9 (100%) | 1.00 / 1.00 / **1.00** | 11/11 | **0%** | 5/5/5/5, 5 |
| 11ty/eleventy | 中型 Node SSG | 9/9 (100%) | 1.00 / 1.00 / **1.00** | 12/12 | **0%** | 5/4/4/5, 5 |

数字的含义：结构提取完全准确；入口 F1 跟随仓库形态——gum 的单入口 CLI 是最好情形，eleventy 的单 Node CLI 同样命中（package.json bin，F1=1.00），click 的纯库布局也能被检测（确定性包根启发式，Roadmap 第 2 项，把 `src/click/__init__.py` 作为 `library_api` 候选产出，LLM 采样确认后把 0.40 置信度提到 0.90、调用方式 `import click`），flask 的 0.67 是贪心召回的设计代价（三个真实入口全中，三个预期误报被重新排序掉），fd 起始为 0.00——已文档化的 Cargo 盲区（尚无 `[[bin]]` 检测；Makefile 候选是误报、`src/main.rs` 是漏报）——当天就被 `[[bin]]`/默认 bin/`[lib]` 启发式关闭：fd 现在 F1=1.00（见 Roadmap 第 4 项）。最硬的保证——0% 幻觉——在**全部五张**报告上都成立（2026-08-27 快照：flask 16/16、click 15/15、gum 18/18；2026-08-30 快照：fd 11/11、eleventy 12/12）。2026-08-27 行是 Roadmap 第 3 项（digest 度量扣分）落地后的复测：报告现在自带确定性 **Verified Facts** 附录（pipeline 计算、绝不经 LLM），judge rubric 豁免与附录匹配的声明。grounding 中位数 3 → 5（gum）、3.5 → 5（flask），correctness/usefulness 随之上升，judge 评论中反复出现的"没有文件内容能自证这个数字"类扣分全部消失；同一 rubric 下无附录的旧 flask 报告仍得 grounding 3——豁免来自附录本身，而非 rubric 放宽。2026-08-30 的运行暴露并修复了一个真实的附录覆盖缺口（eleventy 采样层字节数——`src/UserConfig.js`、`src/Template.js`——未被列出，judge 对正确数字扣分）：附录 largest-files cap 对齐提取器的 15，fd/eleventy 分别 judge 5/5/5/5,5 与 5/4/4/5,5，剩余扣分均为范围外的推断声明（详见 [baseline.md](evals/results/baseline.md)）。

## Roadmap

MVP（Phase 1-8）已完成。下一批杠杆，按价值排序：

1. ~~**收紧证据规则**~~ — **已完成（2026-08-23）**："被引用文件的内容必须自行展示该断言"现在是 prompt 级规则（CLI 契约 + 全部四个 skill prompts），并纳入 judge rubric；已用 `eval --judge` A/B 复测（引用 23→18，0% 幻觉保持，judge 中位数未变——方差主导）。
2. ~~**库盲区**~~ — **已完成（2026-08-24）**：确定性包根启发式（`<pkg>/__init__.py` 或 `src/<pkg>/__init__.py`，≥2 个 .py 文件，排除目录名，仅被 cli/http_server 候选抑制）把导入面作为 `library_api` 候选产出；click 的入口 F1 从 0.00 → 1.00（P=1 R=1），flask/gum 不变（回归护栏），click 报告点名 `src/click/__init__.py`，置信度 0.90、调用方式 `import click`。
3. ~~**digest 度量扣分**~~ — **已完成（2026-08-27）**：报告自带确定性 `digest_facts` 附录，渲染为 **Verified Facts** 节（pipeline 从 `RepoFacts` 计算，绝不经 LLM）；judge rubric 豁免与附录匹配的声明（数值不一致或附录未列出的数字照常扣分）；prompt 契约里悬空的"digest 归因路径"豁免句改为指向该节。零 schema 变更，旧报告渲染逐字节不变。复测（N=3 中位数）：gum 5/5/5/5、click 5/4/5/5、flask 5/5/5/5——grounding 中位数 3→5（gum）、3.5→5（flask）；"没有文件能自证这个数字"类扣分从 judge 评论中消失，且 judge 现在能抓住旧报告"30 天窗口内 1,855 次提交"的融合重算错误。同 rubric A/B：无附录的旧 flask 报告仍得 grounding 3——豁免来自附录而非 rubric 放宽。
4. ~~**更多 gold cases**~~ — **已完成（2026-08-30）**：新增 `sharkdp/fd`（Rust crate）+ `11ty/eleventy`（Node SSG），共五个 case。本次运行文档化了 Cargo 盲区（fd F1=0.00——尚无 `[[bin]]` 检测），并修复了它暴露的附录覆盖缺口（largest-files cap 8 → 15，对齐采样层，LLM 可能重述的每个字节数都在附录里；同时新增 `RepoFacts.from_dict`）。Cargo bin 启发式当天落地——解析树里每一份 `Cargo.toml`（workspace member crate 各自声明自己的 bin）：`[[bin]]` 目标（路径相对 manifest 目录解析，在树内 conf 0.95）、默认 `src/main.rs` bin（conf 0.90），以及默认 `src/lib.rs`/显式 `[lib]` 路径作为 `library_api` 候选（与 Python 包根同一 cli/http_server 门控）；Makefile 规则同步收紧（裸存在不再产出 `build_entry`；`.PHONY` 需含 run/dev/serve/test 关键词）——fd F1 0.00 → 1.00（`src/main.rs`，conf 0.95，`cargo run --bin fd`）。eleventy F1=1.00（package.json bin 正向控制）；旧 case 全部不变（回归护栏保持）；judge N=3：fd 5/5/5/5,5、eleventy 5/4/4/5,5，仅剩范围外的 "implied" 推断扣分。
5. ~~**报告语言覆盖**~~ — **已完成（2026-08-30）**：`REPORT_LANGUAGE=zh` 已端到端打通。渲染层通过确定性翻译表（`report/labels.py`——14 个节标题、头部/表格/行内标签、digest 附录；`en` 保持逐字节不变）本地化，报告记录 `language` key 使 report.json 可独立重渲染，LLM 收到追加指令：自由文本用中文，结构性内容全部钉住（13 个顶层 key、枚举值、路径、符号、数字——翻译枚举会导致 schema 校验失败）。"Verified Facts" 锚点在 zh 下保留（`已验证事实 (Verified Facts, pipeline-computed)`），judge rubric 保持字面有效，并新增"报告可为英文或中文"说明。已在真实 zh click 报告上端到端验证：14/14 中文节标题、0 个被翻译的证据路径、枚举完好（`library_api`/`low`/`high`）、schema 校验通过，judge 得 5/4/4/5,5 且评论为中文。
6. ~~**评估深度**~~ — **已完成（2026-08-30）**，两项升级。
   **分节打分**：judge 现在除了整体五维，还逐节打分（每节 grounding + correctness）——rubric 要求先返回 `sections` 数组再给整体分；解析是宽容的（数组缺失或格式错误时退化为旧的整份报告契约，旧 judge 输出照常解析）。`eval --judge` 会打印分节摘要（数量、均值、任一维度 ≤2 的节名）。已在真实 zh click 报告上验证：13/13 节全部打分、评论为中文，grounding 均值 4.46 / correctness 均值 4.69 与整体 4/4/4/5,5 一致，无弱节。
   **多模型 judge 集成**：可选的第二个 judge provider（`JUDGE_BASE_URL` / `JUDGE_API_KEY` / `JUDGE_MODEL`——base url 与 model 留空时回退主 LLM 配置，只填 key 即可启用）把 `eval --judge` 变成集成：每份报告由两个模型各打一次，flat 分数行取跨模型**中位数**（偶数个取中间两值均值，沿用 baseline.md 的 `.5` 约定），per-model 分数保留在 `models` 行和 JSON 里，分节分数按节名对齐逐节取中位数。不设 `JUDGE_API_KEY` 时单模型契约逐字节不变。judge 调用在解析失败时重试（`MAX_JUDGE_RETRIES`）——推理模型的思维链偶尔吃光 token 预算导致输出截断，一次坏回复不能中止整个 eval 运行。已在真实 zh click 报告上验证（deepseek-v4-flash vs deepseek-v4-pro）：两模型独立给全部 13 节打分、无弱节、correctness 均值同为 4.77；唯一分歧是 grounding——flash 4 vs pro 3（pro 对证据直接性更严）——落中位数 3.5，集成既保留双方共识又削弱任一模型的孤票。

> 注：分析报告本身默认英文输出（`REPORT_LANGUAGE` 可配置），本中文 README 是项目文档的本地化版本。
