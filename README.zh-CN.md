# repo-analyzer-skill

[English](README.md) | 中文

**它是什么：** 一个 Agent Skill，把任意 GitHub 仓库（或本地克隆）转化为结构化、基于证据的分析报告 —— 架构、模块关系、入口、执行流、风险、贡献机会 —— 每条断言都携带文件路径引用，报告发布前会被机械校验。

零运行时依赖，仅标准库。199 个测试。

---

## 为什么做这个

读陌生代码库又慢又容易出错：你猜哪些文件重要，读错一堆，最后得到的理解根本不敢信。通用 LLM 摘要更糟——它自信地编造出仓库里根本不存在的 API、路径和数字。

这个项目要让代码库理解变得**快、可考证、可审计**：

- **快** —— 确定性提取和预算内代码采样几秒完成；LLM 只对精选上下文做推理，从不看整个仓库。
- **可考证** —— LLM 绝不猜测脚本能确定的事实（语言占比、依赖版本、文件数）。每条断言必须引用真实存在的文件路径。
- **可审计** —— 13 节报告 + 自动化证据校验（`verify-evidence`）+ 六指标评估框架（`eval`）。验证不了的断言进 `unknowns`，绝不进报告。

它同时也是 Agent Engineering 的工作演示：Skill 设计、确定性/LLM 边界决策、token 预算下的上下文管理、带修复循环的结构化输出、工具设计、评估。

## 演示

本地模式 —— 零 GitHub API 调用、零 token、零配置：

```
$ repo-analyzer extract .
Extracted facts: output\repos\local\repo-analyzer-skill-cef3623c\repo_facts.json
  repo:        local/repo-analyzer-skill (main @ 6a3f1ad931)
  languages:   Python, JSON, Markdown, TOML
  files:       95 (tree truncated: False)
  manifests:   1
  entrypoints: 1 candidates
  deps:        0 direct
  warnings:    1
    - local mode: metadata is minimal (no stars/issues); language shares are extension-based approximations
```

LLM 推理层产出（真实报告，`examples/reports/pallets-flask/report.md`，deepseek-v4-flash，23/23 条引用全部验证通过）：

> **Summary:** Flask 是一个轻量级 WSGI Web 应用框架，构建于 Werkzeug（WSGI/路由）与 Jinja2（模板）之上，是开发者 import 来构建 Web 应用的核心库包（version 3.2.0.dev）。
>
> **Purpose:** 开发者通过创建 Flask app 对象、注册路由/视图函数、使用蓝图组织模块、处理请求/响应、渲染模板和静态文件来构建 Web 应用。
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
| charmbracelet/gum | 小型 Go CLI | 8/8 (100%) | 1.00 / 1.00 / **1.00** | n/a | n/a | n/a |
| pallets/flask | 中型 Python 框架 | 10/10 (100%) | 0.50 / 1.00 / **0.67** | 23/23 | **0%** | 5/3/3/5, 4 |
| pallets/click | 纯 Python 库 | 10/10 (100%) | 0.00 / 0.00 / **0.00** | n/a | n/a | n/a |

数字的含义：结构提取完全准确；入口 F1 跟随仓库形态（gum 的单入口 CLI 是最好情形；click 的纯库布局没有可确定性检测的入口——LLM 阶段会点名导入面，记录在 case README）；最硬的保证——0% 幻觉——在 flask 报告上成立；judge 给报告打 4/5 分，下一杠杆是收紧直接证据规则。

## 使用

### 安装

```bash
git clone https://github.com/<you>/repo-analyzer-skill
cd repo-analyzer-skill
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"                              # 零运行时依赖；pytest 仅用于开发
```

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

## Roadmap

MVP（Phase 1-8）已完成。下一批杠杆，按价值排序：

1. **收紧证据规则** — judge 给间接引用打了 3/5（grounding）；把"路径必须直接支撑断言"提升为 prompt 级规则，用 `eval --judge` 复测。
2. **库盲区** — click 的入口 F1 是 0.0，因为纯库没有确定性入口；加一个 LLM 阶段的"导入面"候选，让 LLM 点名它。
3. **更多 gold cases** — Go monorepo、Node CLI、Rust crate；每个都往 baseline 加一行，防 prompt 回归。
4. **报告语言覆盖** — `REPORT_LANGUAGE` 已存在；端到端验证并打磨中文渲染路径。
5. **评估深度** — 多模型 judge 集成与分节打分，替代整份报告一个分。

> 注：分析报告本身默认英文输出（`REPORT_LANGUAGE` 可配置），本中文 README 是项目文档的本地化版本。
