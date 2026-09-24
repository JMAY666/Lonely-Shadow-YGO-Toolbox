# 卡片效果结构化标注与语义 TAG 体系

本文是卡片标注体系的规范说明：覆盖范围与口径、效果分段、卡片层与效果层结构、通用效果 TAG、受控词表、审核状态与来源追溯、组合查询语义、更新与复核流程，以及与现有功能的关系。实现位于 `src/trainer/card_annotations.py`、`src/trainer/annotation-tags.json`（词表）与 `src/trainer/card-annotations.json`（内置标注资料）；界面为「资料库 → 卡片标注」模块页；HTTP 入口 `GET/POST /api/annotations`。

**核心边界**：本体系描述卡片的**静态能力**（卡文说了什么）。某张卡此刻能否发动、能否成功结算、是否形成配合，仍由规则引擎与对局状态快照判断；TAG 命中不构成发动判定。这与 1.37.0 关联卡片的口径一致。

## 1. 覆盖范围与清单口径

- 覆盖基数为**当前安装并启用的卡库**：`Catalog` 加载的基础 `cards.cdb` ＋ `expansions/*.cdb` ＋ 已安装超先行补丁（每库记录 sha256）。当前基础库为 14,981 张（含衍生物 265 张；衍生物不参与标注）。
- 覆盖状态按卡逐张给出，七种状态互斥：

| 状态 | 含义 |
| --- | --- |
| `none` 未标注 | 尚无任何已核对或草稿标注。**未标注 ≠ 没有能力**，未知内容保持未知。 |
| `auto` 自动草稿 | 仅有自动提取候选（`origin=auto`），从未人工或引擎核对。 |
| `partial` 部分标注 | 已核对但未覆盖全部效果分段（缺哪段在详情中列出）。 |
| `reviewed` 已核对 | 内置资料人工核对（`origin=manual`）或带历史脚本依据（`origin=engine`，不等于完整引擎验收）且卡文指纹一致，覆盖全部分段。 |
| `confirmed` 已确认 | 用户在本机确认过完整人工标注；自动草稿、部分标注与旧卡文不得直接确认。 |
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
                              conditions（原文条件列表）、fast_effect（是否属于快速效果；不是对方回合可发动的充分条件）
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
                              且要求其卡文指纹与当前一致（脚本映射依据）
notes[]                       效果级备注（含来源引用）
```

无法可靠结构化的内容**不猜**：保留原文于分段文本，未覆盖的分段在详情中显示「未标注」，可加备注说明待处理点。

**同一 TAG、不同参数不可互替**：例如「E-紧急呼唤」（`add_hand`，from=deck）、「暗黑爆发」（`add_hand`，from=grave）与「杀手级调整曲·混音手①」（`add_hand`，from=deck+grave）共享 `etag:add-hand`，但来源区域、筛选条件各不相同，组合查询必须带区域参数才能区分。

## 4. 通用效果 TAG 与受控词表

`annotation-tags.json` 定义 19 个当前通用 TAG 与 1 个兼容旧 TAG（id 形如 `etag:add-hand`），每个含名称、分类、定义、适用范围与同义词；同义词仅用于检索提示，不改变定义。界面分为：资源获取、召唤与展开、除去与转移、无效与干扰、保护与耐性、行动限制、信息与数值、规则与手续。效果伤害与回复基本分分开；旧 `etag:burn` 合并标签保留读取兼容，不用于新样本。

配套受控词表：`zones`（手卡／卡组／卡组顶／卡组底／墓地／除外区／怪兽区／魔陷区／额外（含表侧）／对方区域…）、`actions`（add_hand、special_summon、normal_summon、draw、destroy、banish、send_grave、return_deck、negate_effect、negate_activation、protect、lock、stat_change、deck_reveal、hand_reveal、burn、heal、damage_modify）、`cost_kinds`、`usage_limits`、`timings`。标注校验器强制所有取值来自词表，未登记取值在加载时即报错。

第二批（2026-09-24）按「先查证已有词表未覆盖再登记」扩充了七个受控取值，定义与正反例如下：

| 新增取值 | 定义 | 正例 | 反例 |
| --- | --- | --- | --- |
| `effect_types.no_chain_effect` | 官方补充说明裁定「不属于起动／诱发／诱发即时／永续任一类」的效果（不产生连锁块） | 白骨烤王①②（墓地卡名、代替破坏）、点唱机酒吧“杀手级调整曲”①②、竹蜻蜓电子人①、贝陀螺集合体①、青眼亚白龙①、冰剑龙①、机壳工具 丑恶 p1 | 虹光之宣告者①（官方明确为永续效果→continuous）；青眼亚白龙展示特召手续（官方明确非效果→non_effect） |
| `effect_types.spell_effect` | 魔法效果的发动（非卡片放置时的发动，如从墓地发动的魔法效果） | 红化血染之黄金国永生药②、影灵衣的万华镜② | E-紧急呼唤的通常发动（spell_activation）；自奏圣乐之阶②的墓地陷阱效果（trap_effect） |
| `actions.set_card` | 把魔法·陷阱卡盖放到自己场上 | 转生炎兽 猎鹰①、悲剧之死狱乡演员②、红化血染之黄金国永生药②、转生炎兽的咆哮② | 回到手卡（add_hand） |
| `actions.attach_material` | 把这张卡（及其超量素材）转移为对象怪兽的超量素材 | No.75 惑乱之风言暗影② | 解放（费用 tribute）；作为召唤素材使用（素材规则文本） |
| `cost_kinds.banish` | 把卡除外作为发动费用（来源区域见文字说明） | 相剑大师-赤霄②（手卡·墓地）、白骨王子③（墓地其他卡）、影灵衣的万华镜②（墓地其他卡） | 把墓地的这张卡自身除外（banish_self_from_grave）；作为处理项的除外（action banish） |
| `cost_kinds.send_grave_cost` | 把卡送去墓地作为发动费用（来源区域见文字说明） | 黄金卿①手卡魔法·陷阱、②场上魔法·陷阱；冰剑龙②额外卡组融合怪兽 | 把这张卡从手卡送去墓地（send_grave_self）；处理中的送墓（action send_grave） |
| `cost_kinds.detach_material` | 把这张卡的超量素材取除作为发动费用 | 救祓少女·米迦埃莉丝③、转生炎兽 蜃景雄马①、No.75① | 作为召唤素材使用（旧 `material_as_cost` 不再用于新资料） |

与现有 TAG 的关系：

- 效果 TAG **不进入** `tag-library.json`，不参与卡组／方案的系列自动识别（与用途 TAG 同一纪律），也不改动已有个人 TAG、卡组、方案与备份；
- 查询时可与**系列 TAG／自定义 TAG／用途 TAG** 组合：`tag` 参数接受标签库任意 id（`set:`／`custom:`／`purpose:`），按其成员集过滤；效果 TAG 与结构参数在效果层过滤，两层叠加；
- 反向指向：效果标注的 `selector.series` 可引用系列 setcode（如 `set:1d5` 杀手级调整曲），身份仍是数字系列码。

## 5. 审核状态与来源追溯

- 三个来源层级严格区分：**自动生成**（`origin=auto`，自动草稿，永不计入已核对）、**人工核对**（`manual`，内置资料按卡文逐字核对）、**脚本映射依据**（历史 `engine`，效果编号与脚本映射沿用 `AUDITED_EFFECTS`，要求卡文指纹一致；不代表全部处理、裁定或当前可发动性已通过引擎验收）。
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
- 新卡标注的增量流程：先 `op: draft` 生成自动候选（明确 auto 状态）→ 人工按 §3 结构补全内置资料并运行交接指南中的校验器 → 审核入库。界面仅维护个人备注、标签覆盖和对完整人工标注的确认，不是完整结构编辑器。

## 8. 与其他模块的复用关系

- 卡片身份、卡库加载与来源 sha256 复用 `Catalog`；效果编号映射复用 `card_semantics.AUDITED_EFFECTS` 与其分句规则；原子写入、revision 锁与备份沿用 `plan_library`／TAG 库的既有机制。
- 手坑／解场资料（情报站）、起手分析角色、实战辅助规则各自保持独立用途；本体系不迁移、不覆盖它们，后续可在效果层标注稳定后由这些模块按需引用（引用时以卡号＋效果键定位，不以标签名定位）。

## 9. 当前状态与后续阶段

- **已完成**：规范与实现（分段、校验、覆盖清单、组合查询、自动草稿、个人层）、19 个当前 TAG 与 1 个兼容标签的词表、11 张代表性样本标注（多效果编号、效果内分支、共享／互斥次数限制、灵摆双区、素材规则文本、通常怪兽、无效／除外／破坏／检索／回收／封锁／费用）、第二批 35 张按引擎审计清单（AUDITED_EFFECTS）补全（效果类别以官方 FAQ 補足情報裁定为准，含不产生连锁块效果、墓地／手卡起动效果、诱发即时、永续、墓地魔法效果、盖放、超量素材转移与费用等形态）、界面与接口、单测与验收。
- **进行中／未完成**：全卡库逐卡逐效果标注（当前 14,716 张非衍生物中，46 张已标注，14,670 张尚未标注，按本规范分批推进）；词表按新标注需求扩充；情报站等模块的效果级引用。样本之外的任何能力查询结果均受「已标注范围」限制，不宣称全库准确。

## 10. 1.46.0 复核与兼容要求

- `frozen_text` 保存与 `text_digest` 一致的本地卡文快照。卡文失配时按旧快照展示旧标注，并单列当前原文；旧资料没有快照时明确提示缺失，绝不把新卡文同序号套在旧结构上。
- `sources[]` 保存稳定来源 id、标题、HTTPS URL、`checked_on` 与 OCG/TCG 口径；备注 `source_refs` 指向此表。卡库名称用于显示，卡号用于身份，官方 `cid` 是来源身份，三者不混用。
- `effect_type` 来自新增受控词表，区分起动、诱发、诱发即时、永续、魔法／陷阱卡发动、陷阱效果、灵摆效果与非效果文本。`kind` 仍仅表示分段形式；没有编号不能据此判成非效果。
- `usage_limits` 的旧 `name_soft_opt` 等键仅为兼容名称；同名次数限制不得因键里有 soft 一词而理解为单卡限制。按原文区分「使用」与「发动」，已有标签 ID 不改名。
- 总库数包含衍生物；可标注数与七种状态统计排除衍生物。详情与筛选中的 `partial` 保持一致。`catalog_scope=all` 可浏览未标注卡；无能力条件时无效果卡也可命中。
- 「跨效果命中」只在整卡查询确实需要不同效果满足条件时显示；普通多效果展示不显示。条件仍在效果层逐项匹配，不是同一处理项、同一分支同时可执行的证明。
- 改正了墓指的盖放前提、泡影纵列处理前提、提示员的处理后自锁、自奏圣乐之阶的整回合限制、旋钮手召唤对象与二选一、托马斯的 DDD 子系列与对方全体战斗伤害减半范围。
- 官方规则链接、分类范例与后续智能体的具体交付要求见[标注交接指南](card-annotation-agent-guide.md)。静态参考样本并非穷尽所有特殊裁定。
