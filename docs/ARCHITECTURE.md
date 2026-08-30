# repo-analyzer-skill — Architecture Design (Phase 1)

> 本文档是 Phase 1 的架构设计产出，随项目阶段演进持续更新。

## 1. 需求分解

11 项核心能力按性质分成两组：

| 能力 | 性质 | 归属 |
|---|---|---|
| 基本信息 / 目录结构 / 语言占比 / 依赖 / git 元数据 / 文件统计 | 确定性，API 或解析可得 | 代码 (scripts) |
| Entry point 候选检测 | 半确定性（启发式） | 代码产候选 + LLM 排序解释 |
| 代码样本选择（context management） | 确定性（预算制） | 代码 |
| Architecture / 模块关系 / 执行流 / 风险 / 贡献建议 | 推理 | LLM |
| 引用 (citation) 校验、报告 schema 校验 | 确定性 | 代码 |

## 2. 核心设计决策

### 决策 A：确定性边界 (deterministic boundary)

一切可以通过 GitHub API 或文件解析确定的信息，一律由代码产出。LLM 的输入是「事实库 + 代码样本」，不是原始仓库；LLM 输出推理产物，不输出任何数字。

收益：可靠性（LLM 不会数错文件）、成本（无需 LLM 读全量代码）、可评估（事实可对照 ground truth）、可缓存。

### 决策 B：Fact Base 是契约，不是临时文件

确定性阶段产出版本化的 `repo_facts.json`（schema v1）。下游所有消费者——prompts、LLM 调用、report、eval——只依赖这份契约。这使以下未来能力天然成立：

- **caching**：按 (repo, ref sha) 缓存 fact base，重跑零 API 成本
- **incremental analysis**：新 sha 与旧 sha 的 fact base diff
- **repository comparison**：两个 fact base 直接对比
- **eval**：换 prompt / 换模型不重新抓数据
- **可测试**：单测用 fixtures 直接喂 fact base

### 决策 C：双驱动模式 (dual driver)

- **Agent 驱动**：SKILL.md 定义 agent 如何把 CLI 子命令当 tools 用、拿事实、读代码样本、按 prompts/ 与 workflows/ 分阶段推理、按 schema 产出报告。这是 Claude Code / 通用 agent 里的用法。
- **CLI 驱动**：`repo-analyzer analyze <url>` 端到端跑完（确定性层 + LLM provider 调用），用于 eval、CI、无 agent 环境复现。

两种模式共享：extraction 层、fact schema、prompts、report schema、evidence 校验。同一份知识，两个 driver，不重复实现。

### 决策 E（已确认的技术决策）

- 运行时依赖：**纯标准库**（urllib + tomllib + dataclasses），零第三方运行时依赖；dev 依赖仅 pytest
- 报告语言：**英文**（schema 字段与渲染一致，面向开源与面试）
- 首版 LLM provider：**OpenAI 兼容端点**（base_url + key 均可配置，国内 provider 可直接对接）；Anthropic client 作为后续扩展

### 决策 D：Evidence First 是机制，不是提示词

1. fact base 每条事实自带来源（API 端点 / 文件路径）
2. report schema 中每个断言必须有 `evidence`（文件路径）
3. 报告完成后 `evidence.py` 用确定性手段校验每个引用路径是否真实存在于 tree，输出 verified / unverified 计数

→ hallucination rate 成为可测指标。

## 3. 目录结构

```
repo-analyzer-skill/
├── SKILL.md                  # Skill 入口（frontmatter + 工作流 + 铁律 + 引用清单）
├── README.md                 # 安装、用法、架构说明、样例报告
├── LICENSE                   # MIT
├── .gitignore
├── pyproject.toml            # src 布局；运行时零第三方依赖；dev 依赖 pytest
├── .env.example              # GITHUB_TOKEN / LLM provider / 报告语言 / token 预算
├── docs/
│   └── ARCHITECTURE.md       # 本设计文档
│
├── src/repo_analyzer/
│   ├── config.py             # env 读取与常量（不把 key 写进代码）
│   ├── errors.py             # 类型化错误体系（见 §9）
│   ├── models.py             # fact base / report 的 dataclass（契约的代码形态）
│   ├── github_client.py      # GitHub REST 封装：auth、rate limit、retry、404/私有区分
│   ├── extract/              # 确定性层，每个模块独立可运行、独立可测
│   │   ├── metadata.py       # 仓库元数据
│   │   ├── tree.py           # 目录树（recursive API + truncation 处理）
│   │   ├── languages.py      # 语言统计
│   │   ├── dependencies.py   # manifest 检测 + 多格式解析（tomllib/json/regex）
│   │   ├── entrypoints.py    # 启发式入口候选（含置信度与依据）
│   │   ├── git_stats.py      # 提交活跃度 / 贡献者 / 最近活动
│   │   └── file_stats.py     # 文件大小 / LOC / 热点排行
│   ├── context/
│   │   └── code_sampler.py   # 预算制代码采样（context management 核心）
│   ├── llm/
│   │   ├── base.py           # LLMClient Protocol（provider 抽象）
│   │   ├── openai_client.py  # 首版实现：OpenAI 兼容端点（DeepSeek/Moonshot/Qwen 等均可对接）
│   │   ├── anthropic_client.py  # 后续扩展（MVP 之后）
│   │   └── prompts.py        # 加载 prompts/ 并渲染 fact base 为上下文
│   ├── pipeline/
│   │   ├── facts.py          # 编排 extraction → repo_facts.json
│   │   ├── analyze.py        # 编排完整 pipeline（确定性 + LLM + 校验）
│   │   └── evidence.py       # citation 校验器（确定性）
│   ├── report/
│   │   ├── schema.py         # report schema 代码定义（可导出 JSON）
│   │   └── render.py         # report.json → markdown 渲染
│   └── cli.py                # repo-analyzer CLI（子命令即 tools）
│
├── skill/                    # agent 面层的知识资产（SKILL.md 引用）
│   ├── prompts/
│   │   ├── architecture.md   # 架构推理
│   │   ├── code-flow.md      # 模块关系与执行流
│   │   ├── risk-analysis.md  # 风险 / 复杂度
│   │   └── contribution.md   # 贡献建议
│   └── workflows/
│       └── repository-analysis.md  # agent 分阶段推理工作流
│
├── schemas/
│   └── analysis_report.schema.json  # 权威 schema（从 schema.py 导出，单一来源）
│
├── evals/
│   ├── cases/                # 每 repo 一个 case：gold 标注
│   ├── metrics.py            # 五维指标实现
│   └── run_eval.py           # 评测入口
│
├── tests/
│   ├── unit/                 # mock GitHub 响应的模块级测试
│   ├── fixtures/             # 样例 tree / manifest / API 响应
│   └── integration/          # 本地目录模式端到端
│
└── examples/
    └── reports/              # 真实跑通的报告样例（Phase 6 产出）
```

### 为什么是这个结构（对用户建议的改动说明）

| 改动 | 原因 |
|---|---|
| `scripts/` 平铺 → `src/repo_analyzer/` 包布局 | 平铺脚本无法共享 github_client / models，必然复制粘贴；包布局下每个 extract 模块既是库模块又可独立运行（`python -m repo_analyzer.extract.tree ...`），满足「可单独测试」要求 |
| `workflows/` 移入 `skill/` | prompts 与 workflows 是 agent 面层的知识资产，与 Python 包分离，避免「代码 vs 知识」混淆 |
| 新增 `context/` 与 `report/` | context management 与 structured output 是两个面试核心主题，独立成包并各有职责 |
| 新增 `docs/` | 架构设计文档随阶段演进，作为项目文档资产 |
| `schemas/` 只保留一份权威 JSON | 从 schema.py 导出，单一来源，避免两份 schema 漂移 |

## 4. SKILL.md 设计

```markdown
---
name: repo-analyzer
description: 分析 GitHub repository 的结构、架构、入口、执行流与风险，
             输出带证据引用的结构化分析报告。当用户给出仓库 URL 并希望
             快速理解代码库时使用。
---

## 何时使用
- 输入：GitHub 仓库 URL（或本地路径）
- 参数：分析深度、输出目录、代码 token 预算

## 环境前置
- GITHUB_TOKEN（未设置则降级为未认证 60 次/小时）
- LLM provider 配置

## 工作流（9 步）
1. 校验并解析输入 → 2. 运行确定性提取（CLI 子命令）→ 3. 读取 repo_facts.json
→ 4. 按预算采样代码 → 5. 按 workflows/repository-analysis.md 分阶段推理
→ 6. 按 schema 组装报告 → 7. 运行 evidence 校验 → 8. 渲染 report.md + report.json
→ 9. 自检（unknowns 显式标注）

## 铁律
- 不猜测任何可由脚本确定的事实（语言占比、依赖版本、文件数量……直接引用 fact base）
- 每个断言必须携带 evidence（文件路径）
- 拿不到的数据显式标为 unknown，不编造
- 404 / 私有 / 网络错误按 §9 错误策略走分支，不吞异常不猜原因
```

## 5. Pipeline 与数据流

```
repo URL / 本地路径
      │
      ▼
┌───────────────────────── 确定性层（代码，零 LLM）─────────────────────────┐
│ validate&resolve → metadata → tree → languages → manifests              │
│ → dependencies → entrypoints(启发式) → git_stats → file_stats           │
│ → readme excerpt → code_sampler（token 预算，产出采样清单）               │
│                        │                                                 │
│                        ▼                                                 │
│              repo_facts.json（契约，schema v1）                           │
└────────────────────────┬─────────────────────────────────────────────────┘
                         │
                 ┌───────▼────────┐
                 │ LLM 推理层       │
                 │ P1 architecture │
                 │ P2 modules/flow │
                 │ P3 risks/contrib│
                 └───────┬─────────┘
                         ▼
       report.json（schema 校验）──► evidence 校验 ──► report.md + report.json
```

失败语义：每个 extract 模块独立，个别失败 → fact base 记录 warning，report 对应部分显式标记，不阻断全流程。

## 6. Agent workflow（Agent 驱动模式）

agent 收到 SKILL.md 后执行：

1. `repo-analyzer extract <url>` → 产出 facts 目录
2. 读取 `repo_facts.json`（事实只读一次，不做二次猜测）
3. `repo-analyzer sample-code <url> --budget 40000` → 读采样清单与代码片段
4. 按 `workflows/repository-analysis.md` 分三阶段推理，每阶段读对应 prompt：
   - P1 architecture：fact digest + tree + 顶层概览
   - P2 modules/flow：入口 + 核心文件样本 + P1 结论
   - P3 risks/contrib：事实 + 关键文件 + 报告草稿
5. 按 schema 组装 `report.json`，`repo-analyzer validate-report` 校验
6. `repo-analyzer verify-evidence` → 校验引用，修正未验证引用
7. 渲染 report.md 并呈现

CLI 驱动模式由 `pipeline/analyze.py` 实现同一序列（用 LLM provider 替代 agent 自身推理），保证两种模式行为一致、可复现。

## 7. 输出 schema（analysis_report.schema.json 摘要）

```jsonc
{
  "schema_version": "1.0",
  "repo": { "owner", "name", "url", "ref", "default_branch" },
  "overview": { "summary", "purpose", "evidence" },
  "tech_stack": [ { "category", "name", "version", "role", "evidence" } ],
  "structure": { "summary", "notable_dirs": [ { "path", "purpose", "evidence" } ] },
  "architecture": { "summary", "layers", "data_flow": [ { "from", "to", "mechanism", "evidence" } ], "patterns" },
  "core_modules": [ { "name", "path", "responsibility",
                      "key_symbols": [ { "symbol", "location" } ],
                      "relationships": [ { "with", "mechanism", "evidence" } ],
                      "evidence" } ],
  "entry_points": [ { "path", "kind": "cli|http_server|worker|library_api|scheduler|other",
                      "invocation", "confidence", "heuristic_basis", "rationale", "evidence" } ],
  "execution_flow": [ { "step", "description", "evidence" } ],
  "key_files": [ { "path", "why", "evidence" } ],
  "dependencies": { "direct": [ { "name", "version", "manifest" } ],
                    "notable": [ { "name", "purpose", "evidence" } ],
                    "concerns": [ { "description", "evidence" } ] },
  "risks": [ { "category", "description", "severity": "low|medium|high",
               "evidence", "mitigation" } ],
  "reading_order": [ { "step", "target", "why" } ],
  "contribution_opportunities": [ { "area", "description",
                                    "difficulty", "related_files", "evidence" } ],
  "evidence_summary": { "total_citations", "verified", "unverified", "unverified_list" },
  "unknowns": [ "string" ]
}
```

要点：所有 LLM 产物字段必带 evidence；entry_points 带 confidence 与 heuristic_basis（区分「脚本检测」与「LLM 推理」）；evidence_summary 让可信度可量化。

## 8. 能力归属决策表

| 能力 | 归属 | 理由 |
|---|---|---|
| metadata / tree / languages / deps / git stats / file stats | 脚本 | 确定性，API 可得 |
| entrypoint 候选检测 | 脚本启发式 + LLM 排序解释 | 启发式可穷举（package.json bin、`__main__`、Dockerfile CMD、Makefile、包根 `__init__.py`（library_api 导入面）…），语义解释交给 LLM |
| 代码采样与 token 预算 | 脚本 | 需要精确计算，LLM 无法做到 |
| architecture / 模块关系 / 执行流 / 风险 / 贡献 | instructions + prompts | 纯推理 |
| citation 校验 / schema 校验 | 脚本 | 确定性 |
| 错误分支决策（降级策略） | instructions + 脚本 | 策略在 instructions，执行在代码 |

## 9. Error handling 策略

**错误三分法：**

| 类别 | 例子 | 处理 |
|---|---|---|
| 输入错误 | URL 非 GitHub / 格式错误 | 立即报错，给出正确格式 |
| 上游错误 | 404（不存在 vs 私有）、401、403、429 rate limit、网络 | 类型化异常：`RepoNotFoundError` / `RepoPrivateError` / `AuthError` / `RateLimitError` / `NetworkError`，指数退避重试仅对瞬态错误 |
| 环境错误 | 缺 API key、磁盘写失败 | 启动时校验，明确提示 |

**降级策略（degraded report）：** 每个 extract 模块独立 try/except，失败写 `warnings` 到 fact base；LLM 阶段缺关键事实时，报告对应 section 显式标记 unavailable，不编造。未认证限 60 req/hr → 设计上支持全部缓存响应（Phase 3 起按 sha 缓存）。

## 10. Evaluation 策略（第一天设计）

| 指标 | 方式 | 阶段 |
|---|---|---|
| structure extraction accuracy | 与 git archive 对照（确定性） | Phase 8 |
| entrypoint detection accuracy | precision / recall / F1 vs gold | Phase 8 |
| architecture quality | LLM-as-judge rubric（coverage / grounding / correctness / actionability） | Phase 8 |
| evidence grounding | 确定性 citation 校验（路径是否真实存在于 tree）——存在性由 `evidence.py` 机械检查；"直接支撑"语义由 prompt 规则 + judge rubric 约束（机制无法判断语义）。digest 数字类事实没有能自证的文件路径：报告携带确定性 `digest_facts` 附录（"Verified Facts" 节）承载它们，judge 对照附录判断（2026-08-27）。附录必须覆盖 LLM 可见的全部数字——largest-files cap 对齐提取器（15），即采样器可能把字节数带给 LLM 的每个文件都要在附录里（2026-08-30，eleventy 案例暴露） | Phase 8 |
| hallucination rate | unverified citation 占比 + judge 复核标记的虚假断言 | Phase 8 |
| report usefulness | judge 1-5 + 人工抽检 | Phase 8 之后持续 |

**case 结构：** `evals/cases/<repo>/` 下 `repo.json`（url + 固定 ref，保证可复现）、`gold.json`（gold entrypoints、structure 事实、rubric 目标）、`README.md`（人工标注说明）。评测固定 ref 抓取 → 缓存 fact base → 多种 prompt/模型对比时零额外 API 成本。

## 11. 与面试考察点对应

| 考察主题 | 项目体现 |
|---|---|
| Skill | SKILL.md + skill/ 知识资产，可安装可复用 |
| Agent workflow | 确定性/LLM 边界、分阶段推理、双驱动一致行为 |
| Tool use | CLI 子命令即 tools，每个 extract 模块独立可调 |
| Context management | code_sampler 预算制采样 + 采样清单可审计 |
| Structured output | schema 单一来源 + 校验 + 渲染 |
| Evaluation | evals/ 五维指标 + 固定 ref 可复现 |

## 12. Phase 2–8 路线图

| Phase | 内容 | 交付 |
|---|---|---|
| 2 | 项目骨架 | pyproject、包布局、config/errors/models、CLI 骨架、.env.example |
| 3 | 确定性层 | github_client + 7 个 extract 模块 + facts pipeline + 单测（fixtures） |
| 4 | LLM 推理层 | llm base + anthropic/openai client + code_sampler + 分阶段 prompts + analyze pipeline |
| 5 | 结构化输出 | schema.py + analysis_report.schema.json + render.py + evidence.py |
| 6 | 跑通第一个真实仓库 | 选 1 个中型 repo 端到端 → examples/reports/ + 修复问题 |
| 7 | tests | 单元 + 集成测试（mock GitHub），覆盖核心模块 |
| 8 | eval baseline | 3–5 个 gold cases、五维指标、基线结果文档 |

## 13. 未来能力（设计已预留，不在 MVP）

caching（按 sha）、incremental analysis（fact base diff）、repository comparison、PR/Issue 分析（同一 fact base 契约 + diff 事实）、import-graph 确定性提取（扩展 dependencies 模块）。
