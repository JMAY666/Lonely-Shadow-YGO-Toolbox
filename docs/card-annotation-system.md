# 卡片效果结构化标注与语义 TAG 体系

本文是卡片标注体系的规范说明：覆盖范围与口径、效果分段、卡片层与效果层结构、通用效果 TAG、受控词表、审核状态与来源追溯、组合查询语义、更新与复核流程，以及与现有功能的关系。实现位于 `src/trainer/card_annotations.py`、`src/trainer/annotation-tags.json`（词表）与 `src/trainer/card-annotations.json`（内置标注资料）；界面为「卡片标注」模块页；HTTP 入口 `GET/POST /api/annotations`。

**核心边界**：本体系描述卡片的**静态能力**（卡文说了什么）。某张卡此刻能否发动、能否成功结算、是否形成配合，仍由规则引擎与对局状态快照判断；TAG 命中不构成发动判定。这与 1.37.0 关联卡片的口径一致。

## 1. 覆盖范围与清单口径

- 覆盖基数为**当前安装并启用的卡库**：`Catalog` 加载的基础 `cards.cdb` ＋ `expansions/*.cdb` ＋ 已安装超先行补丁（每库记录 sha256）。当前基础库为 14,981 张（含衍生物 265 张；衍生物不参与标注）。
- 覆盖状态按卡逐张给出，七种状态互斥：

| 状态 | 含义 |
| --- | --- |
| `none` 未标注 | 尚无任何已核对或草稿标注。**未标注 ≠ 没有能力**，未知内容保持未知。 |
| `auto` 自动草稿 | 仅有自动提取候选（`origin=auto`），从未人工或引擎核对。 |
| `partial` 部分标注 | 已核对但未覆盖全部效果分段（缺哪段在详情中列出）。 |
| `reviewed` 已核对 | 内置资料人工核对（`origin=manual`）或经引擎验证（`origin=engine`）且卡文指纹一致，覆盖全部分段。 |
| `confirmed` 已确认 | 用户在本机确认过核对状态。 |
| `pending` 待核对 | 用户标记需要复核。 |
| `stale` 卡文已变化 | 卡库卡文与标注指纹不一致，标注按旧卡文冻结展示，进入复核流程。 |

- 「每张卡都有几个标签」**不**视为完整标注：覆盖清单区分整卡状态与分段覆盖（`full` 要求标注覆盖当前卡文的全部效果分段，或明确 `no_effect`）。
- 覆盖清单实时计算（`op: overview`），不落盘快照；口径随卡库版本变化自动重算。

## 2. 效果分段（效果层的原子单位）

分段器 `card_annotations.segments(desc, type)` 复用 `card_semantics` 的①–⑳编号规则：

- 灵摆卡先按 `【怪兽效果】／【怪兽描述】` 分为灵摆区（键前缀 `p`）与怪兽区（键前缀 `m`）两个文本块，灵摆表头行（`←6 【灵摆】 6→`）剔除；
- 每个文本块内：首个编号前的文本成为 `*-pre`（无编号段，容纳召唤条件、素材规则、次数限制文本）；每个编号成为 `m{n}`／`p{n}`（编号段）；
- 无任何编号的文本块成为单个 `*-all` 无编号段；编号重复等歧义情形整块标记 `ambiguous`，不做强行对应（与 `card_semantics.clauses` 的保守行为一致）。

分段键在**同一卡文指纹**下稳定；指纹变化即整体进入 `stale`，不尝试跨版本对键。

## 3. 标注条目结构

每张卡的标注条目（内置资料 `card-annotations.json` 或本地自动草稿）：

```
code            卡号（整数，身份标识；与 TAG、方案、关联索引一致，不以卡名为身份）
text_digest     卡文 sha256 指纹（与 card_semantics 同一归一化，fail-closed）
review          {status: reviewed|draft, origin: manual|auto|engine, checked_on, basis}
no_effect       通常怪兽等无效果卡的显式声明（覆盖清单计为 full）
effects[]       逐效果标注（见下）
relations[]     效果间关系：material_rule 素材规则 / summon_condition 召唤条件 /
                shared_limit 共享次数限制 / usage_limit_group 次数限制组 /
                exclusive_choice 互斥选择（①②合计1回合1次）/ choose_branch 分支选择 /
                order 顺序 / depends_on 依赖
notes[]         卡片级备注（带 source_refs 来源引用）
```

单个效果的标注：

```
key / block / number / kind   分段标识（哪个效果）
tags[]                        通用效果 TAG（见 §4；只表达共性能力）
structure.activation          发动条件：timing（受控词表）、zones（发动区域）、
                              conditions（原文条件列表）、fast_effect（是否可在对方回合使用）
structure.cost[]              费用：kind（受控词表）＋原文短句
structure.targeting[]         对象要求：count ＋ filter 描述
structure.processing[]        处理内容：action（受控词表）＋count（1 / up_to_1 / all…）＋
                              from_zones / to_zones（资源来源与去向区域）＋
                              selector（可选范围：点名卡、系列 set: id、排除项）＋
                              duration（持续时限）＋restrictions（伴随限制）＋
                              then（顺序后续）／branches[{condition, actions}]（条件分支）
structure.usage[]             使用次数与持续限制（受控词表：soft_opt / name_soft_opt /
                              per_effect_name_soft_opt / shared_name_once / field_once）
engine                        引擎依据：脚本函数名＋发动位置，来自 card_semantics.AUDITED_EFFECTS
                              且要求其卡文指纹与当前一致（引擎验证状态）
notes[]                       效果级备注（含来源引用）
```

无法可靠结构化的内容**不猜**：保留原文于分段文本，未覆盖的分段在详情中显示「未标注」，可加备注说明待处理点。

**同一 TAG、不同参数不可互替**：例如「E-紧急呼唤」（`add_hand`，from=deck）、「暗黑爆发」（`add_hand`，from=grave）与「杀手级调整曲·混音手①」（`add_hand`，from=deck+grave）共享 `etag:add-hand`，但来源区域、筛选条件各不相同，组合查询必须带区域参数才能区分。

## 4. 通用效果 TAG 与受控词表

`annotation-tags.json` 定义 18 个通用 TAG（id 形如 `etag:add-hand`），每个含名称、分类、定义、适用范围与同义词；同义词仅用于检索提示，不改变定义。首版分类覆盖：检索与回收、场面展开、除去与转移、干扰与阻抗、防护、其他功能、规则文本。

配套受控词表：`zones`（手卡／卡组／卡组顶／卡组底／墓地／除外区／怪兽区／魔陷区／额外（含表侧）／对方区域…）、`actions`（add_hand、special_summon、normal_summon、draw、destroy、banish、send_grave、return_deck、negate_effect、negate_activation、protect、lock、stat_change、deck_reveal、hand_reveal、burn、heal、damage_modify）、`cost_kinds`、`usage_limits`、`timings`。标注校验器强制所有取值来自词表，未登记取值在加载时即报错。

与现有 TAG 的关系：

- 效果 TAG **不进入** `tag-library.json`，不参与卡组／方案的系列自动识别（与用途 TAG 同一纪律），也不改动已有个人 TAG、卡组、方案与备份；
- 查询时可与**系列 TAG／自定义 TAG／用途 TAG** 组合：`tag` 参数接受标签库任意 id（`set:`／`custom:`／`purpose:`），按其成员集过滤；效果 TAG 与结构参数在效果层过滤，两层叠加；
- 反向指向：效果标注的 `selector.series` 可引用系列 setcode（如 `set:1d5` 杀手级调整曲），身份仍是数字系列码。

## 5. 审核状态与来源追溯

- 三个来源层级严格区分：**自动生成**（`origin=auto`，自动草稿，永不计入已核对）、**人工核对**（`manual`，内置资料按卡文逐字核对）、**引擎验证**（`engine`，效果编号与脚本映射沿用 `AUDITED_EFFECTS`，且要求其卡文指纹与当前卡库一致）。
- 每个内置条目记录 `checked_on`、`basis` 与卡文指纹；内置资料文件头记录核对时的卡库 sha256（`verified_against`）。运行时另附当前 `Catalog.sources` 的逐库 sha256。
- 个人修正存于 `<runtime>/_trainer/card-annotations.json`（`revision` 乐观锁、原子写入、每次保存前备份到 `backups/annotations/<revision>.json`）：核对状态翻转、效果备注、效果 TAG 增删（对内置标签的增删记为个人覆盖，可撤销）。人工内容在卡库更新时保留。
- 冲突提示：卡文指纹失配 → `stale`，旧标注冻结展示并提示复核；同版重复导入不重复写入。

## 6. 组合查询语义（`op: query`）

- 条件分两层：卡片层（关键词、类型、标签库 TAG、状态）与效果层（效果 TAG 多选 any/all、动作、来源区域、去向区域、次数限制、费用、发动时点）。
- **默认范围 `scope=effect`**：所有效果层条件必须在**同一效果**内成立；同一张卡的不同效果不串用条件。
- `scope=card`：允许各条件由不同效果分别满足，但每个条件仍须指出由哪个效果命中；命中跨多个效果时结果明确标注「跨效果命中」。
- 每个命中给出依据：条件名、取值、依据文案（TAG 定义／处理项选择器／隐含去向等）、效果原文与编号、状态与来源；`to_zone` 未显式标注时按动作隐含去向匹配并注明「隐含去向」。
- 查询只在已标注范围内进行，结果同时给出 `annotated_total` 与 `catalog_total`：**未标注卡片不代表没有该能力**。

## 7. 更新与复核流程

- 卡库或超先行补丁更新后 `Store.reload_resources()` 会重建 `Catalog` 并 `CardAnnotations.reload()`：指纹一致的标注照常；失配的转 `stale` 冻结；个人备注与核对标记保留；内置资料中已不在卡库的卡列入 `missing_codes`。
- 恢复能力：内置资料随版本管理（Git 历史）；个人层每次保存留有 revision 备份。
- 新卡标注的增量流程：先 `op: draft` 生成自动候选（明确 auto 状态）→ 人工按 §3 结构补全 → 状态翻转为已核对。批量审核通过界面状态筛选逐批确认，复核记录进 revision 备份链。

## 8. 与其他模块的复用关系

- 卡片身份、卡库加载与来源 sha256 复用 `Catalog`；效果编号映射复用 `card_semantics.AUDITED_EFFECTS` 与其分句规则；原子写入、revision 锁与备份沿用 `plan_library`／TAG 库的既有机制。
- 手坑／解场资料（情报站）、起手分析角色、实战辅助规则各自保持独立用途；本体系不迁移、不覆盖它们，后续可在效果层标注稳定后由这些模块按需引用（引用时以卡号＋效果键定位，不以标签名定位）。

## 9. 当前状态与后续阶段

- **已完成**：规范与实现（分段、校验、覆盖清单、组合查询、自动草稿、个人层）、18 个通用 TAG 词表、11 张代表性样本标注（多效果编号、效果内分支、共享／互斥次数限制、灵摆双区、素材规则文本、通常怪兽、无效／除外／破坏／检索／回收／封锁／费用）、界面与接口、单测与验收。
- **进行中／未完成**：全卡库逐卡逐效果标注（14,716 张非衍生物卡当前均为 `none`，按本规范分批推进）；词表按新标注需求扩充；情报站等模块的效果级引用。样本之外的任何能力查询结果均受「已标注范围」限制，不宣称全库准确。
