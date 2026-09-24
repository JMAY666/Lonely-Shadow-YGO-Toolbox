# 1.45.0 验证记录 · 卡片效果结构化标注首期

日期：2026-09-24。范围：`src/trainer/card_annotations.py`、`src/trainer/annotation-tags.json`（18 个通用效果 TAG ＋受控词表）、`src/trainer/card-annotations.json`（11 张代表性样本）、`src/trainer/app.py`（`/api/annotations` 路由、静态白名单、Store 挂载与资源重载）、`src/trainer/web/card-annotations.js/.css` 及导航接入、`desktop/card-annotations-smoke.cjs`、`tests/test_card_annotations.py`、`tests/card_annotations_view.test.cjs`。

## 1. 覆盖清单（真实卡库，2026-09-24 实测）

- 卡库：基础 `cards.cdb`，14,981 张，sha256 `5f13245de4e665450858f66ef2f736a3d2f48cc7f0036961373a96a650cb6797`（无扩展库与已安装补丁）；内置标注资料 `verified_against` 已记录同值。
- 覆盖状态（`op: overview`）：已核对 11、未标注 14,970、其余状态 0；可标注范围 14,716（衍生物 265 不参与）。
- 11 张样本全部分段覆盖（`full=true`），其中 3 张（杀手级调整曲·提示员／旋钮手／混音手）挂接引擎验证映射（`AUDITED_EFFECTS` 指纹一致时自动附带脚本函数与发动位置）。
- 口径说明：未标注 ≠ 没有能力；「每张卡有几个标签」不作为覆盖依据，覆盖按分段计算。

## 2. 正确性用例（代表性正确与错误用例）

正确用例（均通过）：

1. **同 TAG 不同参数**：`etag:add-hand`＋来源区域=卡组 → E-紧急呼唤、旋钮手②B、混音手①、自奏圣乐之阶②；同 TAG＋来源=墓地 → 暗黑爆发、混音手①。共用标签不导致互相替代，E-紧急呼唤不出现在墓地来源结果中。
2. **条件不跨效果**：`etag:special-summon`＋`etag:banish`（全部命中，默认单效果范围）→ 0 命中（样本中无单效果兼有二者）；切整卡范围 → 命中提示员且标注「跨效果命中」，依据分别指向 m1／m2。反向说明：托马斯 m1 单一效果内同时破坏＋特召，单效果范围即命中——说明"跨效果"限制针对的是条件串用，不是禁止复合效果。
3. **次数限制组合**：`action=special_summon`＋`usage=per_effect_name_soft_opt` → 仅提示员①。
4. **费用筛选**：`etag:negate-effect`＋`cost_kind=discard_self` → 仅灰流丽①。
5. **负例（未知≠没有）**：状态筛选 `none` ＋任一条件 → 0 命中；未标注卡（如灵摆样本之外的 14,970 张）从不出现在任何查询，同时 `annotated_total/catalog_total` 一并返回。
6. **卡文变化冻结**（合成卡库单测）：修改卡文并 `reload_resources` 后状态转 `stale`、旧标注冻结展示、`status=reviewed` 筛选不再命中该卡；个人备注保留。
7. **自动草稿**：草稿状态恒为 `auto`，丢弃后回到 `none`；草稿条目仅含词表模式匹配证据，不含人工／引擎依据。

错误用例（构造无效数据，均按预期拒绝）：

- 未登记 TAG（`etag:not-registered`）、效果键不在当前分段（`m9`）→ 服务加载即报错（fail-closed）。
- 词表版本不符、TAG 无分类／无定义 → `Registry` 构造报错。
- 旧 revision 提交 → 「本地标注已更新，请刷新后重试」；备注定位越界 → 报错不误删。

## 3. 查询耗时（真实卡库，本机实测）

当前已标注宇宙（11 张）：

| 查询 | 命中 | 平均 | 最大 |
| --- | --- | --- | --- |
| 加入手卡＋来源=卡组 | 4 | 0.05ms | 0.54ms |
| 加入手卡＋来源=墓地 | 2 | 0.02ms | 0.03ms |
| 动作=特殊召唤＋同名各1回合1次 | 1 | 0.02ms | 0.04ms |
| 效果无效＋费用=丢自身 | 1 | 0.01ms | 0.02ms |
| 特召＋除外（整卡范围） | 1 | 0.03ms | 0.04ms |

全卡库规模推演（内存中为全部非衍生物卡生成草稿构成 11,843 张已标注宇宙，验证线性扩展）：分段 14,716 张 49ms、生成草稿 211ms、覆盖清单 11ms；组合查询 26–113ms（无过滤全列 98ms）。结论：查询成本随已标注数量线性增长，当前架构可承载全量标注的日常查询；未做索引优化，后续如需再评估。

准确性对比口径：同一查询在服务层与界面（真实 Electron 渲染）各执行一次，结果一致（桌面冒烟第 2 节）；界面额外展示逐条命中依据。自动草稿的命中数量（如全库 add-hand 2,895）仅代表词表模式覆盖率，不作为准确性指标。

## 4. 已执行检查

- `python -m unittest tests.test_card_annotations`：12 项通过（分段、同 TAG 参数隔离、跨效果限制、状态筛选、覆盖统计、指纹失配、草稿流程、标签覆盖、无效资料拒绝、词表校验、草稿证据）。
- `node --test tests/card_annotations_view.test.cjs`：8 项通过（效果标签、类型徽章、依据行、分支渲染、结构行、结果列表、详情状态、覆盖条）。
- `npm test`（全部 Python 单测＋237 项前端单测）：通过。
- `node desktop/smoke.cjs --annotations-only`（真实 Electron＋内嵌服务＋真实卡库）：通过——概览数字、界面墓地来源查询与排除项、详情引擎验证／次数限制组／自锁限制、备注保存、核对状态翻转、自动草稿生成与丢弃、个人层落盘 `_trainer/card-annotations.json`。
- `npm run test:desktop`（完整默认档，真实 Electron＋原生引擎训练）：71 项检查全部通过、无页面错误（证据 `.local/evidence/electron-development/result.json`）；含导航清单更新（新增「卡片标注」入口）。
- 未执行：`npm run test:packaged`（需先 `npm run build:dir` 产出 1.45.0 成品包；本次未构建新包，发布时执行）。`npm run test:modular` 未运行（本次未改模块化路径；1.44.0 已全量通过，无相关变更）。

## 5. 边界与未验证事项

- 样本外的 14,705 张可标注卡未标注；任何全库能力统计均受「已标注范围」限制，不宣称全库准确。
- 自动草稿为保守正则候选：只产生 TAG／动作骨架与证据片段，不含费用、对象、次数等结构（人工补全）；「除外状态」等易混淆表达已做排除，但不保证零误报。
- 引擎验证状态依赖 `AUDITED_EFFECTS` 的卡文指纹；指纹失配时该状态自动消失（降级为普通已核对）。
- 静态标注不判断当前局面可发动性；与实战辅助、模块化求解的关系仅为数据引用，未接入。
- `docs/recording.md` 提及的 report 版本号差异（文档 v8 vs 代码 14）为历史遗留，与本次无关，未处理。
