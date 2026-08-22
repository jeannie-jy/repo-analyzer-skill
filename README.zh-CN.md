# repo-analyzer-skill

[English](README.md) | 中文

一个可复用的 **Agent Skill**：把任意 GitHub 仓库转化为结构化、基于证据的分析报告。

给定仓库 URL，它会：

1. **确定性提取事实** — metadata、目录树、语言统计、依赖、入口候选、git 统计，全部用纯 Python 完成，不经过 LLM。
2. **把事实 + 预算内代码样本喂给 LLM**，做架构推理（模块关系、执行流、风险、贡献机会）。
3. **输出 schema 校验通过的报告**，其中每条断言都携带可验证的文件路径引用。

设计为双驱动：**[SKILL.md](SKILL.md)** 驱动 agent 走完整工作流；同一套管线以 CLI（`repo-analyzer`）暴露，保证可复现、可测试、可评估。

## 状态

| Phase | 内容 | 状态 |
|---|---|---|
| 1 | 架构设计 | ✅ 完成（[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)） |
| 2 | 项目骨架 | ✅ 完成 |
| 3 | 确定性提取层 | ✅ 完成 |
| 4 | LLM 推理管线 | ✅ 完成 |
| 5 | 结构化输出 + 证据校验 | ✅ 完成 |
| 6 | 第一个真实仓库端到端 | ✅ 完成（[examples/reports/pallets-flask](examples/reports/pallets-flask/)） |
| 7 | 测试 | ✅ 完成（170 个测试） |
| 8 | 评估基线 | ✅ 完成（[evals/results/baseline.md](evals/results/baseline.md)） |

## 安装

需要 Python 3.11+。**零运行时依赖** — 仅标准库。

```bash
git clone https://github.com/<you>/repo-analyzer-skill
cd repo-analyzer-skill
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e ".[dev]"          # dev extra 仅安装 pytest
```

## 配置

```bash
export GITHUB_TOKEN=...          # 可选但强烈建议（60 -> 5000 次请求/小时）
export LLM_BASE_URL=...          # 任意 OpenAI 兼容端点
export LLM_API_KEY=...
export LLM_MODEL=...
```

完整选项见 [.env.example](.env.example)。配置也可写入仓库根目录的 `.env` 文件（已 gitignore，不会提交）。

## 用法

```bash
repo-analyzer analyze https://github.com/pallets/flask
```

管线各阶段暴露为子命令（每个也可作为 agent 驱动模式下的工具）：

```bash
repo-analyzer extract https://github.com/pallets/flask
repo-analyzer sample-code https://github.com/pallets/flask --budget 40000
repo-analyzer validate-report output/repos/pallets/flask/report.json
repo-analyzer verify-evidence output/repos/pallets/flask/report.json
repo-analyzer eval --judge            # 对照 gold cases 给报告打分
```

输出写入 `output/repos/<owner>/<repo>/`：`repo_facts.json`（事实基座）、`sample_manifest.json`（采样清单）、`analysis.json`（LLM 分析）、`report.json` / `report.md`（带 grounding 摘要的最终报告）。

## 作为 Agent Skill 使用

把仓库（或 `SKILL.md` + `skill/`）复制/软链到你的 agent 的 skills 目录。工作流：解析输入 → 提取事实 → 读 facts digest → 预算内采样 → 按 4 个 prompt section 推理 → schema 校验（含修复循环）→ 机械验证每条引用 → 渲染报告。完整规范见 [SKILL.md](SKILL.md)。

核心约束（Iron Rules）：**LLM 只做推理，绝不重新猜测脚本能确定的事实**；每条断言必须带文件路径证据；拿不到的显式标为 unknown，不编造。

## 设计

完整架构见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — 确定性/LLM 边界、`repo_facts.json` 契约、evidence-first 报告机制、评估策略。

> 注：分析报告本身默认英文输出（`REPORT_LANGUAGE` 可配置），本中文 README 仅是项目文档的本地化版本。
