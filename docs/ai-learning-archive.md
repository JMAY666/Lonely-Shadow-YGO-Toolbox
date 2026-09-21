# AI 学习计划封存与 Git 历史回溯

**状态：已由用户主动停止并封存，2026-09-21。** 用户明确要求“整理并核实历史记录”。本次保留现有实现和全部历史，没有撤回原提交、重置分支、删除实验资料或修改远程地址。原预算和历史后续事项停止执行，恢复须由用户明确提出。

封存基准为 `ae8ee353827be47412c2f907a8144b6a3a14fa68`（`experiment: 完成40家族教师验证并版本化预算`），即本次封存修改之前的干净 `main`。已重新 fetch 并核对当时远程 `main` 指向同一提交。封存收尾文档是之后单独的提交，不计入下面截至基准的 10 次实验计划提交。

## 停止时的成果与未完成项

- P0A 的本地 GPU 训练、恢复与 CPU 导出探针已完成；P0B/P1 在限定机制和连续执行范围通过。
- P2 冻结 200 家族、120/40/40 划分；P3 修复后完整验证为 T0 29/40、B1 26/40，80 次重放/归档审计通过，331 个搜索窗口隐藏信息替换检查通过。
- 小试质量方向通过，配对 95% 区间仍为 −5 至 +20 个百分点；保守成本 5.112 小时超过原已批准的 5 小时门槛，整体结论仍是“部分可行”。
- worker 历史累计约 118.01 分钟。账面剩余 61.99 分钟仅是封存时的记录，不再构成执行额度。
- P4 扩大采样、正式学生学习、留出评测、LLM 对照、能力更新和产品接入均未继续；40 个 holdout 家族保持封存。停止状态不等于计划已经完成。

[原计划](ai-learning-feasibility-plan.md)、[完整验证结果](ai-learning-p3-validation-v8-results.md)及[实验说明](../experiments/ygo_learning/README.md)继续保留。停止检查时没有本项目实验进程运行，也没有找到以该计划路径或名称配置的 Codex 自动任务；本次未启动任何引擎、GPU、LLM 或训练。

## 本地封存内容

独立封存目录：`.local/archives/ai-learning-stopped-20260921/`，沿用 `.gitignore`，仅保存在本机。原始目录与资料均保留原处，封存采用复制，不是迁移。

| 文件 | 内容与验证 |
| --- | --- |
| `history.bundle` | 截止基准 `main` 的完整 Git 可达历史，`git bundle verify` 通过，无外部前置提交依赖 |
| `workspace-objects-ae8ee35.zip` | 从 Git 原始 blob 导出的 440 个源码/文档文件，每个文件均按 Git 对象哈希核对，ZIP CRC 通过 |
| `evidence.tar` | 133,458 个本地文件，原始内容 16,245,257,222 字节（约 15.13 GiB），TAR 16,484,904,960 字节；每个成员完整读回并核对 SHA-256 |
| `evidence-files.jsonl` | 原文件相对路径、大小、修改时间和 SHA-256 的逐文件清单 |
| `evidence-summary.json` | 封存范围、文件数、字节数、完整归档哈希与校验结果 |
| `git-history.json` | 逐提交时间、实际文件变化、插入/删除行数、推送 reflog 与远程可达性证据 |
| `origin-main-reflog.txt` | 本机远程跟踪分支 reflog 的原始导出 |
| `source-history-checks.json` | 源码快照、历史 bundle 与历史索引的 SHA-256 |
| `seal_evidence.py`、`trace_history.py` 与日志 | 本次封存和只读核验过程，保留换行转换诊断和最终成功结果 |

首次 `git archive` 受本机 Git 换行转换影响，导出的 `workspace-ae8ee35.zip` 没有通过逐字节原始对象校验；最终使用上表的原始 blob ZIP，并验证全部 440 个文件。自动审批以 `blocked by policy` 拒绝清理首次生成的约 4.43 MiB 重复 ZIP，因此该文件作为诊断保留，不用它作为精确源码副本。本次没有删除原文件或实验资料。

实验副本包括 `.local/ygo-learning/` 全部 98,307 个文件，以及前置依赖 `.local/ygo-agent-pilot/` 全部 31,185 个文件；还包括开发版/打包版 native、learning-p1、learning-p2-p3、learning-p3-correction、ygo-agent-pilot 十组验收 profile 的 `_trainer/` 数据和对应正式验收证据。共享 native 验收目录按停止时状态保存，不能据目录中的每个文件都认定是本计划新产生的。

Git bundle 和源码 ZIP 保留整个仓库基准，以便保留其他功能与必要上下文；下面的历史清单才用于界定计划范围。本地副本包含虚拟环境与模型，但仍可能依赖本机 Python 路径，恢复时依据锁定文件核对，不将其视为独立可移植安装包。

封存校验摘要：

| 产物 | SHA-256 |
| --- | --- |
| `history.bundle` | `a383a85677833e71be99b84f14ff7dba377568ef051622b8d11830e2d09030d5` |
| `workspace-objects-ae8ee35.zip` | `72950743c8be953c993dfc73e8503a0d22ab92a1181ea03e10fcd4f68b8e9da5` |
| `evidence.tar` | `e6a29b5a82308311df5fffc00d4965862e64b080f1603116ba93b4c591d425c0` |
| `evidence-files.jsonl` | `c517123b936736bcc0473d37ef8867c222b46000f2880800ff5dcb12b6720ab3` |
| `git-history.json` | `dde8d87d24f9ddc91fff323ef7f270fd1dc72745c37361f0ee160e8d6738f918` |

## 10 次直接相关提交和推送

直接范围依据计划文件自身的完整提交历史，以及每次提交的全部变更核对。共 10 次提交、136 次文件变更，涉及 77 个不同路径；累计 diff 插入 8,772 行、删除 529 行，包含对同一文件的多次修订，不能当作最终净新增行数。

时间均为北京时间（UTC+8）。提交时间来自 Git commit；推送时间来自本机 `refs/remotes/origin/main` reflog 的 `update by push`。重新取得远程引用后，以下提交全部可从远程 `main` 到达。reflog 是本机操作证据，不是 GitHub 服务器审计日志。

| 提交 | 提交时间 | 推送时间 | 文件数 | 内容 |
| --- | --- | --- | ---: | --- |
| [aac7526](https://github.com/JMAY666/Lonely-Shadow-YGO-Toolbox/commit/aac75260cd9faccc54b1bd0acbe95772cd794e8c) | 09-19 11:03:38 | 09-19 11:04:24 | 2 | 制定本机 AI 推演与模型学习验证计划 |
| [6708d71](https://github.com/JMAY666/Lonely-Shadow-YGO-Toolbox/commit/6708d71399d46397a304cbb8c6ad236cec66b4dd) | 09-19 11:15:26 | 09-19 11:16:18 | 2 | 补充 GPU 推理实测与学生训练验证路线 |
| [2234928](https://github.com/JMAY666/Lonely-Shadow-YGO-Toolbox/commit/2234928deb2aa4003d21132de33f0ad139a72cf8) | 09-19 11:51:28 | 09-19 11:51:31 | 11 | AMD GPU 学生训练、恢复与 CPU 导出 |
| [3606625](https://github.com/JMAY666/Lonely-Shadow-YGO-Toolbox/commit/3606625cde2e47f6e1182740e11d59a05b366cfd) | 09-19 12:11:41 | 09-19 12:11:44 | 2 | 根据 GPU 验收重排验证计划 |
| [e5f8a8f](https://github.com/JMAY666/Lonely-Shadow-YGO-Toolbox/commit/e5f8a8f3586d9d8a0ea89a75968b07a7abea3e8d) | 09-19 14:40:00 | 09-19 14:40:28 | 34 | 动态契约、学生连续执行、原生学习快照与重放 |
| [ea5f969](https://github.com/JMAY666/Lonely-Shadow-YGO-Toolbox/commit/ea5f969b2dacb08b291200440d71b920d75a80de) | 09-20 15:26:42 | 09-20 15:27:22 | 16 | 冻结 P2 协议、实现 T0 教师并标定 |
| [512f84e](https://github.com/JMAY666/Lonely-Shadow-YGO-Toolbox/commit/512f84ef09461a79f99e84ec00728803a2e389e8) | 09-21 10:56:15 | 09-21 10:56:56 | 15 | 教师纠偏、公共动作提案与无损原生证据归档 |
| [82b37d4](https://github.com/JMAY666/Lonely-Shadow-YGO-Toolbox/commit/82b37d441d778f51a766e0982e5183b9fabb4e20) | 09-21 12:48:18 | 09-21 12:48:36 | 32 | 资源/时间优化、部分验证、原生焦点死锁修复 |
| [f25a1b4](https://github.com/JMAY666/Lonely-Shadow-YGO-Toolbox/commit/f25a1b4ca054cd8e383b5d9bdee8b8e01ea416d3) | 09-21 13:46:21 | 09-21 13:47:12 | 6 | 修复后二进制完整训练标定与预算复核 |
| [ae8ee35](https://github.com/JMAY666/Lonely-Shadow-YGO-Toolbox/commit/ae8ee353827be47412c2f907a8144b6a3a14fa68) | 09-21 14:54:09 | 09-21 14:54:58 | 16 | 版本化 3/5 小时预算、完整 40 家族验证与成本停止结果 |

远程配置仍为 `https://github.com/JMAY666/Lonely-Shadow-Yu-Gi-Oh-Toolbox.git`；GitHub 当前规范仓库名为 `JMAY666/Lonely-Shadow-YGO-Toolbox`，仓库 ID `1369989861`，旧地址正常跳转。没有更换远程、分支或标签。

## 前置试验与穿插提交

前置试验 [17af5b7](https://github.com/JMAY666/Lonely-Shadow-YGO-Toolbox/commit/17af5b7d82ba7b8616b9a75ee37bca7b1d21cfbc) 于 09-19 10:15:28 提交、10:16:14 推送，涉及 12 个文件，为旧 `ygo-agent` 本机逐步指导验证。它先于本计划产生，单列为来源依赖，不计入上表 10 次提交。本计划开始前的仓库基准是 `e282f5d423b920c0ef837dd27435835da7edb531`。

从 `aac7526` 到 `ae8ee35` 共有 19 个线性提交，其余 9 次属于并行进行的产品工作：

| 提交 | 内容 |
| --- | --- |
| `b094ccf` | 撤回 BO1 后攻计划实现 |
| `949f358` | TAG 关联卡片管理 |
| `ef0cb8c` | 情报站终场标注、手坑与断点管理 |
| `db41967` | 终场来源标注与并列备注 |
| `a7387d5` | 情报站工作区布局与编辑体验 |
| `a79037f` | 手坑效果标记与并列备注 |
| `f7b8bdc` | 常用手坑与解场效果分类资料 |
| `59d555f` | 主流卡组阻抗图解与分环境资料库 |
| `03e2020` | 对手构筑资料与两级主题导航 |

这 9 次提交也已核对推送记录和远程可达性，详细时间在本地 `git-history.json`。不能把整个连续提交区间都归为本计划。

## 涉及的产品共用代码

77 个不同路径中，51 个在 `experiments/ygo_learning/`，12 个为计划/契约/结果文档，另 14 个含仓库入口、前置试验 README 和共用实现/测试。完整逐提交路径清单保存在本地 `git-history.json`。

- `e5f8a8f` 修改了 `patches/ygopro-lite.patch`、`scripts/apply_lite.py`、`src/lite/training_history.cpp`、`training_learning.inc`、`training_modular.inc`、`training_support.cpp/.h`，包含动态属性、学习快照与重放支持。
- `82b37d4` 修改了共用原生支持与补丁，还涉及 `src/trainer/app.py`、`desktop_host.py`、新增的 `learning_fixture.py`、`tests/test_learning_fixture.py` 和 `desktop/smoke.cjs`，包含测试条件导入、计时与焦点锁死锁修复。
- 这些提交的实际内容不止独立实验脚本；本次只核对并封存，现有产品代码与已经通过的共用修复保持原状。

## 本次核验边界

本次完成停止状态记录、资料复制、哈希与 Git 历史核验，113 个本地文档链接与封存状态 JSON 一致性检查通过。没有重新进行模型/教师实验，没有重新跑应用或桌面验收，也没有把过去的通过结果称为本次复测。历史记录未撤销或改写，本地原始文件未删除或迁移；所有封存包继续仅保存在本机。
