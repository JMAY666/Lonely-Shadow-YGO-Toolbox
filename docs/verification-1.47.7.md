# 1.47.7 验证记录 · 四个完整系列新增 96 张

日期：2026-09-25。先依据当前 `.local/YGOPro-Lite` 的 `Catalog` 与 `CardSeries` 重算，保存[96 个不同本地整数卡号的候选及最终清单](card-annotation-batch-2026-09-25-phase4.csv)，随后核对本地完整 `name/type/desc`、KONAMI 官方 OCG 卡片页及 FAQ 补足情報。官方站内用户牌组评论不作裁定；官方 `cid`、系列 `setcode`、本地异画卡号分开记录，未改本地译名。

## 覆盖与来源

| 项目 | 实际结果 |
| --- | --- |
| 原覆盖／新增／新覆盖 | 402／96／498 张 |
| 当前非衍生物可标注／尚未标注 | 14,716／14,218 张 |
| 已有复核后跳过／本批新条目核对中修正／待核对 | 0／6／0 张 |
| 闪刀 | 新增 47；系列 47／47 |
| 半龙女仆 | 新增 22；系列 22／22 |
| 斩机 | 新增 16；系列 16／16 |
| 军贯 | 新增 11；系列 11／11 |

本阶段 96 个本地编号对应 81 个不同官方 `cid`。14 个未直接出现在辅助映射中的本地异画编号仅在同名、同类型、同完整卡文指纹与基础卡一致后映射至官方卡页，仍逐号保存。新增条目均有 `frozen_text`、现有 `digest()` 指纹、`segments(desc,type)` 全段、效果结构、OCG 规则地区、核对日期与备注来源引用；原有 402 条逐项不变。《舍利军贯》是通常怪兽，保留完整叙述并标 `no_effect`；其官方 FAQ 无额外补足条目，依据官方卡片页核对。81 个官方卡页与 FAQ 原始 HTML 仅保留在 `.local/anno-batch7-research/`，不进入 Git 或安装包。

本批核对中纠正 6 处新条目：光／暗连接素材可任意组成两只，并非必须各一；《闪刀机关-多任务战刀机》①限制的是己方魔法卡的**卡片发动**后对方的连锁；《随兴捏军贯》①展示手卡舍利是可选发动手续；《慈爱之贤者-西埃拉》②移交己方怪兽控制权；《军贯处『海栈』》②与《推荐捏军贯》②要求对方支付基本分。没有覆盖旧资料或留下未解决裁定。静态结构及 TAG 命中不保证特定局面可发动，也不表示互斥分支能同时处理。

## 分批检查

累计 20／40／60／80／96 张时逐批运行实际 runtime 的标注与系列校验、本阶段官方来源快照／指纹／全分段核查和关键机制正反查询，检查旧 402 条不变。边界包含效果送墓与费用送墓、发动无效与效果无效、对方额外怪兽区与己方额外怪兽区、非效果召唤手续与融合／同调／超量素材、对方支付基本分与效果伤害、不同分支的次序。官方 FAQ 明确分类的 128 个本批编号怪兽效果与结构类别交叉比对，未发现类别不一致。新增受控区域和动作的定义、正反例、兼容规则与校验见[体系规范](card-annotation-system.md)。

## 最终验收

| 命令 | 实际结果 |
| --- | --- |
| `python scripts/check_card_annotations.py --runtime .local/YGOPro-Lite` | PASS 498；词表、来源、冻结卡文、当前指纹和全部分段 |
| `python scripts/check_annotation_series.py --runtime .local/YGOPro-Lite` | PASS 20 个展示系列／35 个代表样例；四个本批系列另由专项检查确认全员 `reviewed/full` |
| `python scripts/check_annotation_batch7.py --runtime .local/YGOPro-Lite --expected 96 --require-snapshots` | PASS 96；96 个本地卡号的 OCG 卡页／FAQ 快照、逐效果来源引用及机制查询正反例 |
| `npm test` | PASS；576 项 Python、246 项 Node 测试通过 |
| `npm run test:desktop -- --annotations-only` | PASS；`annotations-result.json` 的 `errors=[]`、`globalInput=false` |
| `npm run build:dir` | PASS；1.47.7 当前源码目录构建，离线资源清单 28,888 项 |
| `npm run test:packaged -- --annotations-only` | PASS；EXE 品牌及七种图标帧，打包标注验收 `errors=[]`、`globalInput=false` |

桌面与首次打包验收分别使用唯一 `YGO_TEST_RUN=annotations-1477-20260925-45c14f32`、`annotations-1477-packaged-20260925-3566c3c8`，通过后台 Electron 与隔离测试数据执行，不移动系统鼠标或发送全局按键。测试、构建及打包日志保留在 `.local/anno-batch7-*.log`，正式截图和 JSON 证据在 `.local/evidence/`。文档写入后再次用当前源码重建并复验当期包，确认包内标注资料、词表、README、规范、交接指南、清单和记录与工作区 SHA-256 一致。个人 TAG、备注、牌组、方案、备份和个人标注不写入；AI 学习计划继续封存。来源快照、正式证据及包保留本地。
