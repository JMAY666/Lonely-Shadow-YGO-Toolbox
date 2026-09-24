# 卡片标注体系 · 现状与缺口分析（2026-09-24）

本文件记录建立统一卡片效果标注与语义 TAG 体系前的现状盘点与缺口结论，作为 1.45.0 首期建设的依据。现状结论均给出代码位置；缺口即本期实现范围（见 [标注规范](card-annotation-system.md)与[验证记录](verification-1.45.0.md)）。

## 1. 卡库与卡片身份（已具备，直接复用）

- 统一卡库服务 `Catalog`（`src/trainer/app.py:123`）：基础 `cards.cdb`（14,981 张，sha256 `5f13245d…`，2026-09-01 批次）＋ `expansions/*.cdb` ＋ 已安装超先行补丁，逐库记录 sha256；卡片按**整数卡号**索引，字段含类型位、setcode（4×16 位系列打包）、卡文与 str1–16。
- 卡片身份在 TAG 成员（`plan_tags.contains_card`）、关联索引（`card_relations.py`）、方案与构筑中一致使用卡号；系列身份为数字 setcode。**新体系直接沿用，不引入第二身份。**
- 资源更新路径已有：`Store.reload_resources()` 重建卡库并失效缓存；超先行补丁安装／回滚有事务与校验（`superpre.py`）。

## 2. 效果级既有能力（部分具备，需统一）

- **卡文分句**：`card_semantics.clauses()`（①–⑳、编号歧义即放弃）是权威实现；另有 `intelligence_marks.effect_parts` 等多处轻量重复（仅支持到⑩）。缺口：无统一分段服务、无灵摆双区／前置文本的结构化键。本期 `card_annotations.segments()` 统一（p*/m* 键、前置段、灵摆双区、ambiguous 保守标记）。
- **效果-引擎映射**：`card_semantics.AUDITED_EFFECTS`（约 40 张人工审核卡：卡文 sha256 指纹＋[(效果编号, 引擎描述符, 发动位置, Lua 函数)]），`effect_clause()` 用其把引擎事件定位到具体效果编号，指纹失配即降级。缺口：覆盖面小、仅服务回看展示。本期将其作为**引擎验证状态**接入标注条目（`engine` 字段），并沿用其指纹纪律。
- **脚本静态引用**：`card_relations.script_references()` 已能提取 Lua 数字点名（不执行脚本）。可继续为标注的 selector 提供依据。
- **对局状态与事件**：`native.jsonl` 事件流、完整引擎快照（`training_support.cpp`）、live 独立状态账本（`live_duel_state.py`）齐备。**静态标注与这些运行时判断明确分离**（本体系不越界）。

## 3. TAG 体系（已具备，效果 TAG 缺位）

- 现有四类：系列 `set:`（strings.conf＋series-official.json）、自定义 `custom:`、用途 `purpose:`（手坑／解场，与情报站资料同源）、效果 TAG（`custom:`＋`purpose:effect`，由 staples 导入生成，本质是**卡片成员清单**）。均存于 `_trainer/tag-library.json`，revision 乐观锁＋原子写入＋备份。
- 系列／用途／效果 TAG 均不参与主副系列自动识别（`deck_tags.py:44` 跳过 `kind=purpose`；效果 TAG 同纪律）。
- **缺口**：没有表达"能力语义"且逐效果挂接的通用 TAG——现有效果 TAG 只回答"哪些卡"，不回答"哪个效果、什么条件、什么参数"。本期 `annotation-tags.json`（18 个 etag＋受控词表）补此层，且不进入 tag-library、不参与自动识别，查询时可与系列／自定义／用途 TAG 组合。

## 4. 逐效果资料（局部存在，口径不一）

- 情报站手坑／解场：`staples.json`（64 卡、28+39 份、checked_on 2026-09-20）＋ `staples-texts.json`（卡文快照），导入合并带 unmatched_effects 待核对（`intelligence_marks.merge_marks`）。
- 实战辅助：`live-duel-rules.json`（27 卡逐效果 response/limit/flags，卡文不符即停用）。
- 起手分析：`opening_workspace.reviewed_effects`（角色来自 staples 分组＋护航卡号硬编码）。
- **缺口**：三套各自为政、按用途挑卡；没有全量覆盖清单，没有"未标注／部分／待核对／已核对"的统一口径，没有结构化的发动／费用／对象／处理／次数字段。本期以统一条目结构与七态覆盖清单承接，三套资料保持原用途不迁移。

## 5. 检索（卡片级已有，效果级缺失）

- 卡片级：`Catalog.search`（关键词／类型／属性／种族／等级／收藏／TAG 成员），`/api/cards`。
- **缺口**：无法按"效果能力＋来源区域＋去向＋次数限制"组合查询，无法给出效果级命中依据，无法防止同卡不同效果串用条件。本期 `op:query`（默认单效果范围、逐条依据、整卡范围显式标注跨效果）补齐。

## 6. 审核与更新纪律（惯例已备，需集中）

- 既有惯例：卡文 sha256 指纹失配即降级（AUDITED_EFFECTS）、提交卡文必须等于当前卡库（`intelligence.annotation`）、效果文本不一致转待核对（`merge_marks`）、资源重载失效缓存。
- **缺口**：没有区分 auto／manual／engine 三来源的统一状态模型，没有覆盖清单驱动的复核流程与个人修正层。本期：七态状态机、`<runtime>/_trainer/card-annotations.json` 个人层（revision 锁＋备份）、自动草稿生成器（明确 auto、可丢弃）。

## 7. 全量覆盖现状（起点数字）

| 口径 | 数量（本期实测） |
| --- | --- |
| 卡库总卡数 | 14,981 |
| 衍生物（不参与标注） | 265 |
| 可标注范围 | 14,716 |
| 带①–⑳编号效果的卡 | 10,128 |
| 灵摆卡 | 399 |
| 首期已核对样本 | 11（全分段覆盖；含 3 张引擎验证） |
| 其余 | 未标注（`none`；未知 ≠ 没有能力） |

分批推进建议：① 以 AUDITED_EFFECTS ∩ 常用构筑为先（引擎证据现成）；② 手坑／解场 64 卡（卡文快照已有）；③ 按系列 TAG 逐系列推进；④ 自动草稿仅作待核对候选，不追覆盖率数字。
