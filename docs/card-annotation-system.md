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
structure.targeting[]         对象要求：固定 count、min_count/max_count 区间或动态 count_rule ＋ filter 描述；
                              max_count: null 显式表示无固定上界
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

固定且内容已知的获赋效果可放入 `structure.processing[].granted_effect`，只允许对应动作是 `grant_effect`，其内部必须有 `effect_type`、`tags` 和完整 `structure`。父段使用 `own_tags` 明确自身标签，父段 `tags` 是自身与固定子效果标签的并集；子效果也经过词表、费用、快速标志与 TAG／处理一致性校验。为保留旧处理树遍历，`grant_effect.then` 须与子 `structure.processing` 完全一致，防止两份描述分叉。

查询分别在父段自身及各固定子效果内匹配所有条件，命中仍返回原分段键，但依据标明固定获赋来源和路径。个人 TAG 移除对整个段的匹配生效，个人新增标签按父段保留；不写回或迁移个人资料。没有这组元数据的旧 `grant_effect.then` 保持原行为；`copy_effect` 的对象和能力未知，不允许借固定获赋字段展开。详情页单独显示获赋效果的时点、费用、次数及另行发动／适用边界。

**同一 TAG、不同参数不可互替**：例如「E-紧急呼唤」（`add_hand`，from=deck）、「暗黑爆发」（`add_hand`，from=grave）与「杀手级调整曲·混音手①」（`add_hand`，from=deck+grave）共享 `etag:add-hand`，但来源区域、筛选条件各不相同，组合查询必须带区域参数才能区分。

## 4. 通用效果 TAG 与受控词表

`annotation-tags.json` 定义 20 个当前通用 TAG 与 1 个兼容旧 TAG（id 形如 `etag:add-hand`），每个含名称、分类、定义、适用范围与同义词；同义词仅用于检索提示，不改变定义。界面分为：资源获取、召唤与展开、除去与转移、无效与干扰、保护与耐性、行动限制、信息与数值、规则与手续。效果伤害、回复基本分和伤害防止分开；旧 `etag:burn` 合并标签保留读取兼容，不用于新样本。

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

第三批（2026-09-24）按同一流程为手坑／解场 62 张扩充三个受控取值，定义与正反例如下：

| 新增取值 | 定义 | 正例 | 反例 |
| --- | --- | --- | --- |
| `actions.set_position` | 变更场上怪兽的表示形式（表侧/里侧·攻击/守备） | 月之书①（变里侧守备）、日全食之书①（全部变里侧及其结束阶段变表侧）、敌人操纵器①第一分支 | 把魔法·陷阱卡盖放（set_card）；特殊召唤时的表示形式指定（`position` 字段） |
| `actions.take_control` | 得到对方怪兽的控制权（时限与伴随限制见结构说明） | 心变①、精神操作①、敌人操纵器①第二分支、三战之才第二● | 接触的G②（封锁素材使用，不夺取控制权）；洗回卡组（return_deck） |
| `cost_kinds.remove_counter` | 把场上指示物取除作为发动费用（种类与数量见文字说明） | 海龟坏兽 加美西耶勒④（坏兽指示物×2）、怪粉坏兽 加达拉④／怒炎坏兽 多哥兰④（×3）、黏丝坏兽 库莫古斯④（×2） | 把超量素材取除（detach_material）；解放怪兽（tribute） |

本轮系列补标登记十五种处理取值；它们保留处理差异，不自动推导通用能力 TAG：

| 新增取值 | 定义 | 正例 | 反例与兼容规则 |
| --- | --- | --- | --- |
| `actions.apply_trigger_effect` | 适用被选怪兽本应作为同调素材送墓后发动的效果；具体能力随所选卡而变，不能为此自动挂被复制效果的 TAG | 杀手级调整曲播放列表①、响度战争② | 自己实际发动的检索等效果继续用原动作；旧条目不迁移 |
| `actions.grant_extra_attack` | 赋予怪兽同一战斗阶段额外攻击次数 | 杀手级调整曲 B2B② | 攻击力上升用 `stat_change`；旧条目不迁移 |
| `actions.choose_branch` | 单次处理中从 `branches` 选择一个互斥分支；容器本身不构成能力，实际能力只在子项表达 | B2B③手卡回收或特召、同调超车①回收或特召 | 先后都执行用 `then`；不能把各分支解释成一次发动可同时执行；旧条目不迁移 |
| `actions.use_as_fusion_material` | 效果处理选定怪兽作融合素材，实际送达区域受其他效果影响；不能等同固定送墓 | 烙印融合①从手卡／卡组／场上取两只素材 | 发动费用中的送墓用 `cost_kinds.send_grave_cost`；普通融合召唤素材规则不作为此效果动作；旧条目不迁移 |
| `actions.negate_attack` | 使一次已宣言的攻击无效，独立于无效效果或发动 | 轩辕之相剑师①自身特召成功后无效该次攻击 | 灰流丽无效效果用 `negate_effect`，自奏圣乐之阶无效发动用 `negate_activation`；旧条目不迁移 |
| `actions.discard_hand` | 效果结算时从手卡选卡丢弃；与发动费用分离 | 驱魔姐妹圣母悼歌①先检索两只，后丢弃一张 | 灰流丽丢弃自身作为费用用 `cost_kinds.discard_self`；旧条目不迁移 |
| `actions.detach_material` | 效果结算中取除超量素材 | 驱魔姐妹・卡尔麦尔②处理时取除全部素材 | 米迦埃莉丝③发动费用用 `cost_kinds.detach_material`；旧条目不迁移 |
| `actions.change_effect` | 把对方正在处理的效果改为指定处理，不表示无效发动或效果 | 驱魔姐妹・卡尔麦尔②将响应效果改为从对方墓地回收一张 | 赤霄②的效果无效用 `negate_effect`；旧条目不迁移 |
| `actions.grant_effect` | 当前效果赋予另一张卡或本卡以后才能发动的效果；子处理注明未来的条件，不当作立即执行 | 转生炎兽・翠玉鹰②解放连接怪兽后赋予战斗开始时破坏与伤害 | 立即破坏用 `destroy`；旧条目不迁移 |
| `actions.use_as_ritual_material` | 仪式魔法结算中选用并处理仪式素材；其解放或替代回卡组发生在处理时，随后才仪式召唤 | 转生炎兽的降临①使用手卡／场上怪兽，满足条件时可将墓地系列怪兽回卡组替代 | 发动费用解放用 `cost_kinds.tribute`；融合素材用 `use_as_fusion_material`；旧条目不迁移 |
| `actions.modify_summon_material` | 改变召唤所需素材或可用素材方式，不把召唤本身伪装成效果处理 | 转生炎兽的圣域①允许同名连接怪兽单独作素材 | 炽焰融合①结算中实际取融合素材用 `use_as_fusion_material`；旧条目不迁移 |
| `actions.equip_card` | 通过效果把魔法卡装备到被特召或指定的场上怪兽 | 炽焰飞腾①把本卡装备到刚从墓地特召的怪兽 | 单纯改变攻击力用 `stat_change`；旧条目不迁移 |
| `actions.grant_piercing` | 装备卡给予攻击守备怪兽时的贯通战斗伤害规则；具体伤害由战斗结算，不作效果伤害 | 转生炎兽的烈爪② | 给予效果伤害用 `burn`；旧条目不迁移 |
| `actions.lose_lp` | 效果处理使自己失去基本分，不能算作给予对方效果伤害或发动时支付费用 | 天威龙・太阳蟠龙②特召成功后失去连接标记数乘1000基本分 | 轩辕之相剑师的支付费用用 `cost_kinds.lp`；旧条目不迁移 |
| `actions.place_field_spell` | 从卡组／墓地把场地魔法表侧放置在场地区域 | 天威无穷之境地③放置天威无崩之地 | 盖放魔陷用 `set_card`；旧条目不迁移 |

后续完整系列补标新增 `actions.place_faceup_card`：把永续魔法或永续陷阱从墓地等指定来源表侧放置到魔法陷阱区。正例为《烙印之兽》②把墓地的「烙印」永续魔法／陷阱表侧放置；反例为《白之烙印》②把自身盖放（继续用 `set_card`）以及《天威无穷之境地》③把场地魔法表侧放置（继续用 `place_field_spell`）。旧条目不自动迁移，`from_zones`／`to_zones` 仍须显式校验。
`actions.modify_activation_window` 表示持续改变指定卡片效果可发动的回合或时点，正例为《自奏圣乐的通天塔》①让己方自奏圣乐连接怪兽及墓地怪兽效果在对方回合也可发动；反例为自身已经属于诱发即时效果的《自奏圣乐之阶》①。该动作不复制或发动其他效果，不推导其实际处理 TAG；旧条目不自动迁移。
青眼系列另登记 `actions.allow_direct_attack`（卡文允许的直接攻击，正例《青眼卡通究极龙》①；反例只是提高攻击力的《青眼光龙》①）与 `actions.require_attack_payment`（攻击宣言时的强制支付，正例《青眼卡通龙》②；反例《杀手级调整曲·红印鉴唱片师》③的效果发动费用）。两者都不等于一次可发动效果的费用或效果伤害；旧条目不自动迁移，适用条件继续由结构校验和分段备注约束。
影灵衣系列另登记 `actions.end_battle_phase`：结束当前战斗阶段，正例《瓦尔基鲁斯之影灵衣》①先无效攻击成功后结束战斗阶段，反例《轩辕之相剑师》①只无效该次攻击。`actions.tribute` 表示效果结算中解放怪兽，正例《瓦尔基鲁斯之影灵衣》②结算时解放手卡／场上最多两只怪兽后抽卡；反例《青眼精灵龙》③发动时解放自身费用（继续用 `cost_kinds.tribute`）及非效果特殊召唤手续中的解放。二者均保留旧条目兼容，不自动重写既有结构；新条目仍由受控词表、来源区和逐项校验约束。
召唤兽系列另登记 `actions.attack_in_defense`，正例《召唤兽 科库托斯》②允许自身以表侧守备表示攻击并按攻击力计算战斗；反例《转生炎兽之炎军》第一分支只是以守备表示特殊召唤怪兽，并不赋予攻击权。该动作不是追加攻击次数或贯通伤害；旧条目不自动迁移，来源依据和适用区域须随结构说明。

2026-09-26 为超重武者扩充 `attack_in_defense.damage_calculation_stat`：`atk` 表示按攻击力、`def` 表示按守备力进行伤害计算。原来没有该字段的条目继续保持 `atk` 含义，不重写《召唤兽 科库托斯》的旧记录。正例《超重武者 大弁庆-K》②和《超重荒神 须佐之男-O》①明确使用 `def`；反例是单纯提高守备力，不能因此推导守备表示攻击权，也不把伤害计算数值替代解释为改变怪兽实际攻击力。

全库来源接收与急袭猛禽／超重武者核对增加下列明确取值，旧条目不自动迁移：

| 取值 | 定义和必需参数 | 正例 | 反例 |
| --- | --- | --- | --- |
| `actions.place_pendulum` | 从 `from_zones` 把卡放到 `to_zones: ["pendulum"]`，不视为卡片发动或特殊召唤 | 超重神童 牛若-U4 的灵摆①及怪兽② | 灵摆召唤继续用 `special_summon`；盖放魔陷用 `set_card` |
| `actions.redirect_attack` | 正在进行的攻击改为攻击指定对象，`selector.text` 说明对象；立即伤害计算另行标明 | 超重武者 松明-2 的攻击转移 | 无效攻击用 `negate_attack`，不能把二者混用 |
| `actions.copy_effect` | 从明确来源取得指定卡的效果，须有 `selector`、`from_zones` 与 `duration` | 急袭猛禽-起翼叛逆猎鹰③ | 授予已知固定效果使用 `grant_effect`；不能猜测复制对象并自动新增其能力 TAG |
| `actions.prevent_damage` 与 `etag:prevent-damage` | 令承受伤害变为0；`damage_scope` 为 `battle`／`effect`／`battle_and_effect`，`recipient` 为 `self`／`opponent`／`both`，`duration` 必填 | 急袭猛禽-战备②同时防止自己受到的战斗与效果伤害 | 给予效果伤害用 `burn`；回复基本分用 `heal`；旧 `damage_modify` 的战斗伤害范围保持不变 |
| `effect_types.spell_continuous` | 魔法、灵摆或作为装备魔法使用的卡持续适用且不产生连锁块的效果 | 超重武者装留的装备状态持续效果、超重辉将 珊瑚-5 的灵摆刻度变更 | 装备状态中需要发动并产生连锁的效果仍用 `spell_effect`，不能标为快速效果 |

无效果卡的核对也须依据官方类型或明确补充说明：通常怪兽的描述不产生效果 TAG；无效果的融合、同调、超量、连接和仪式怪兽不等于通常怪兽，其素材条件和仪式说明以 `non_effect`、素材规则标签及关系单独保留。不能依据标签为空或辅助身份索引的 `has_effect` 字段，直接把卡标为无效果。

`usage_limits.name_summon_method_once` 专门表示同名卡按指定方法特殊召唤每回合最多一次，正例为《超重武者 隐密-32》的该方法特召限制；反例是同名效果每回合只能使用一次，继续按原有效果次数取值记录。旧次数字段不迁移，不把方法特召次数混同效果发动／使用次数；召唤无效等个别处理仍由来源备注限定。
神碑系列另登记 `zones.extra_monster_zone` 表示自己的额外怪兽区域，正例《黄金之雫的神碑》①第二分支从额外卡组把神碑怪兽特召到该区域；反例为《青眼精灵龙》③只写从额外卡组特召、未限定必须在额外怪兽区域的效果。`monster`／`field` 查询可包含已明确标记的这一子区域，反向查询不能从笼统 `monster` 推断必定可用额外怪兽区域；旧条目不迁移。

闪刀系列增加 `zones.opponent_extra_monster_zone` 表示对方的额外怪兽区域；正例《闪刀术式-爆风偏向》①只把该区域的对方怪兽回卡组，反例为《闪刀亚式-双纽闪门》①可选双方任意场上卡。`opponent_monster`、`monster`、`field` 广义查询可包含明确标记的对方额外怪兽区域；反向不能由笼统怪兽区推断特定额外怪兽区域。旧条目不自动迁移，来源／去向按官方处理记录。

闪刀系列增加 `actions.use_as_link_material`：效果连锁处理后立即以己方场上怪兽作连接素材进行连接召唤，正例《闪刀亚式-双纽闪门》②；反例《闪刀姬-零衣》①直接从额外卡组特召而不作连接召唤，继续用 `special_summon`。新动作须登记怪兽区素材来源和后续连接召唤，不能把素材误当发动费用；旧条目不自动迁移。
闪刀系列另增加 `actions.equip_as_spell`：把怪兽卡作为装备魔法卡置于魔陷区并装备给指定怪兽，正例《闪刀姬-阿泽莉娅·节制》①将对方怪兽装备给自身及《闪刀机-正义刀剑》②把墓地自身装备给系列连接怪兽；反例《炽焰飞腾》①装备原本就是魔法卡的本卡，仍用 `equip_card`。新动作须显式记录来源和魔陷区去向；不把怪兽卡当作通常召唤或特殊召唤。旧条目不自动迁移。
斩机系列增加 `actions.change_level`：明确把怪兽等级改成指定值并登记适用时限，正例《斩机 乘武》①把己方4星电子界族怪兽暂时当8星；反例《斩机刀 那由他》①只增加攻击力，继续用 `stat_change`。等级变更不推断为攻击力变更或特殊召唤，旧条目不迁移。
斩机系列另增加 `actions.use_as_xyz_material`：效果连锁处理后立即以指定场上怪兽作超量素材进行超量召唤，正例《斩机超阶乘》①第二分支；反例《驱魔姐妹们的圣母颂歌》③只是把指定卡叠作已有超量怪兽素材，继续用 `attach_material`。新动作须登记怪兽区素材来源及后续超量召唤，不把素材伪装成发动费用；旧条目不自动迁移。
军贯系列新增 `actions.treat_as_name`：在明确区域把卡片按另一个卡名使用，正例《赤舍利军贯》①在手卡、卡组、场上、墓地视为《舍利军贯》；反例《舍利军贯》本身原名已是该名，不产生名称替代。名称替代不改变效果怪兽为通常怪兽。新增 `actions.place_counter`：效果处理时在表侧卡上放置指定数量的指示物，正例《推荐捏军贯》①在自身放1个；反例《军贯处『海栈』》①将卡置于卡组顶并不放指示物。两项须登记来源区域或数量，旧条目不自动迁移。
闪刀与军贯补充 `actions.give_control`、`actions.require_lp_payment`：前者是己方怪兽把控制权交给对方，正例《慈爱之贤者-西埃拉》②；反例《闪刀机-黑寡妇抓锚》①取得对方怪兽控制权仍用 `take_control`。后者是效果结算中要求指定执行者支付基本分，正例《军贯处『海栈』》②要求对方支付触发怪兽守备力、《推荐捏军贯》②要求对方支付指示物数乘500；反例《星杯的守护龙 阿尔玛杜克》②给予效果伤害继续用 `burn`，自身基本分被效果扣除则用 `lose_lp`。支付处理须显式登记执行者，不产生效果伤害 TAG；旧条目不自动迁移。

后续六系列核对新增 `actions.return_grave`：表侧除外卡回墓地，正例《龙辉巧-天棓三β》①；反例《铁兽战线 弗拉克杜尔》①卡组送墓继续用 `send_grave`，前者不推导送墓 TAG。`actions.increase_normal_summon_limit` 表示提高本回合可通常召唤次数，正例《随风旅鸟×雪猫头鹰》①；反例《随风旅鸟×知更鸟》①处理后立即召唤，继续用 `normal_summon`。`actions.negate_summon` 表示在非入连锁的召唤之际无效该次召唤，正例《龙辉巧流星群》①；反例《卫星闪灵·红色精灵》②无效对方怪兽效果，继续用 `negate_effect`。`actions.substitute_tribute_cost` 表示用墓地卡除外替代其他怪兽效果的解放费用，正例《天斗辉巧极》②；反例《龙辉巧-右枢α》①确实解放怪兽作为费用，继续用 `cost_kinds.tribute`。新动作均登记来源／去向或时限，不自动迁移旧条目。
`usage_limits.up_to_two_per_turn` 表示同一效果每回合最多发动两次，正例《龙仪巧-天龙流星DAD》②，官方确认同一连锁可发动两次；反例《巨大喷流卫星闪灵》②仅每回合一次。该次数键不推导同链资格，具体限制继续写入效果条件及备注。既有 `grant_piercing` ID 扩为不限装备来源的贯通规则：正例《随风旅鸟×雪猫头鹰》②的怪兽区持续赋予，旧正例装备卡《转生炎兽的烈爪》②仍适用；效果伤害仍用 `burn`，不自动迁移旧结构。
`actions.return_unsummoned` 记录召唤被无效、怪兽尚未入场时回持有者手卡或额外卡组，正例《随风旅鸟与恐怖之海》①；反例《铁兽的死线》②把已在场上战斗的怪兽回手，仍用 `return_hand`。新动作校验去向，广义回手 TAG 可检索到，但不会把被无效的召唤误判为怪兽已在场上；旧条目不自动迁移。
`actions.substitute_detach_source` 记录取除超量素材费用时允许改从另一只己方超量怪兽下取除，正例《十二兽的相克》①；反例《十二兽 龙枪》②确实从本卡下取除，继续用 `cost_kinds.detach_material`。新动作须显式登记 `xyz_material` 来源，不把费用替代错算成该卡效果结算时取除素材；旧条目不自动迁移。
既有 `actions.return_hand` 的场上来源校验兼容 `opponent_monster` 和双方额外怪兽区等已登记子区域，正例《铁兽的死线》②把对方场上怪兽回手；反例是对方墓地卡回手，应使用 `add_hand` 并记录 `opponent_grave`。该兼容扩展不把墓地卡误判为场上弹回，也不改写旧条目。

白森林系列新增 `actions.treat_as_tuner`：把对象暂时视作调整，正例《白森林的魔女》③；反例为本身原本就是调整的《白森林的阿斯忒瑞亚》，无需此处理。此项必须记录适用时限；离开怪兽区或变里侧后的中止条件在处理限制中写明。新增 `actions.use_as_synchro_material`：效果处理后立即以己方场上怪兽为素材进行同调召唤，正例《白森林的幻妖》②；反例为卡片本身的同调素材要求，后者只属于规则段。新动作需登记怪兽区素材来源和后续同调特殊召唤，素材不是发动费用。新增 `actions.return_hand`：场上卡经效果回持有者手卡，额外卡组怪兽按规则回额外卡组，正例《蓟花之赦免》①；反例为《影灵衣的万华镜》从墓地回收仪式卡，用 `add_hand`。场上来源必须显式登记，查询层把这类处理映射为「加入手卡」TAG；这三个动作均不自动迁移旧标注。

本轮同时登记 `zones.xyz_material` 表示附在超量怪兽下的素材，正例是驱魔姐妹们的圣母颂歌③作为素材的己方超量怪兽返回额外卡组，反例是墓地中的怪兽；已有墓地/怪兽区标注不自动迁移。`cost_kinds.return_deck` 表示把明确来源的卡返回主卡组或额外卡组作为发动费用，不限于手卡；来源、持有者、去向以及适用的顶底／洗牌方式须在 `cost.text` 中说明。正例包括驱魔姐妹・伊雷娜①的手卡「驱魔姐妹」回卡组底；若官方卡文要求墓地卡回额外卡组作为费用，也沿用该 ID 并明确来源及去向。反例为效果处理的回卡组，仍用 `actions.return_deck`；费用不产生回卡组能力 TAG。旧条目不自动迁移，不通过新定义替旧资料补全未知来源。
`timings.end_phase` 只用于明确在结束阶段发动的效果，正例为转生炎兽・郊狼①，反例为先前发动、结束阶段才执行延迟处理的卡尔麦尔①；旧时点不自动迁移。

与现有 TAG 的关系：

- 效果 TAG **不进入** `tag-library.json`，不参与卡组／方案的系列自动识别（与用途 TAG 同一纪律），也不改动已有个人 TAG、卡组、方案与备份；
- 查询时可与**系列 TAG／自定义 TAG／用途 TAG** 组合：`tag` 参数接受标签库任意 id（`set:`／`custom:`／`purpose:`），按其成员集过滤；效果 TAG 与结构参数在效果层过滤，两层叠加；
- 反向指向：效果标注的 `selector.series` 可引用系列 setcode（如 `set:1d5` 杀手级调整曲），身份仍是数字系列码。

### 短魔法／陷阱的规则与辅助动作（2026-09-26）

下面新增 15 个动作，沿用既有逐效果结构。它们描述本卡实际进行的处理；不会把被影响、被转移或后来发动的另一张卡的抽卡、破坏、无效等能力自动赋给本卡。每个新增动作都须有非空 `selector.text`。字段里的玩家取值为 `self`／`opponent`／`both`；`executor` 指处理执行者，`recipient`、`player`、`controller` 则按各字段说明指受影响玩家或卡片控制者。

| 新动作 | 定义与必需参数 | 正例 | 反例与 TAG 边界 |
| --- | --- | --- | --- |
| `remove_counter` | 效果处理取除指示物；记录 `counter_type`（种类文字或 `all`）、`from_zones`、`count`（正整数或 `all`） | 指示物吸除器（38834303）取除全部指示物；魔力枯竭（95451366）只取除魔力指示物 | 发动时取除用 `cost_kinds.remove_counter`；不推导破坏／送墓／除外 |
| `place_deck_top` | 将选定卡放至卡组最上面；须有 `executor`、`from_zones`、`to_zones`（仅 `deck_top`／`opponent_deck_top`）、`count`、布尔值 `shuffle_before_placement`；提供 `inspects_opponent_deck` 时须为布尔值 | 翡翠虫笛（95214051）由对方选择并洗切后置顶 | 不是主动确认卡组的 `deck_reveal`。沿用包含卡组顺序操作的 `etag:deck-look`；该 TAG 本身不证明可以查看对方整副卡组 |
| `reveal_set_cards` | 确认场上盖卡内容而不改变表示形式；须有场上 `from_zones`、`count`、`controller`、`audience` 和 `changes_position=false` | 旧神之印（97809599）、心灵透视（75392615）确认对方盖卡 | 翻成表侧用 `set_position`；不借用确认手卡 TAG |
| `change_hand_limit` | 改变规则手卡上限；记录 `recipient`、非负整数 `value`、`duration` | 圣书体石板（10248192）本决斗自己上限7张 | 不是抽到指定手卡数，也不立即丢弃手卡 |
| `skip_phase` | 跳过指定玩家的指定阶段；记录 `player`、`phase`、正整数 `count`、`duration`，重叠适用规则另放 `restrictions` | 刻之封印（35316708）跳过下次对方抽卡阶段 | 不是抽卡能力，也不是结束当前战斗阶段 |
| `repeat_phase` | 指定阶段重复进行；字段同上，`count` 为总次数且至少2，`duration` 明确适用起点 | 不运的报告（19763315）令对方下次实际进行的战斗阶段进行2次 | 不是追加攻击次数，也不强迫对方进入战斗阶段 |
| `advance_turn_count` | 推进单张卡正在计算的回合数；记录所选卡 `count` 和推进量 `amount`，均为正整数 | 命运之火钟（1082946）推进1张卡的回合计数1回合 | 不推进真实回合、不代替准备阶段次数，不推导计数届满后的破坏能力 |
| `redirect_spell_recipient` | 将只适用于一位玩家的魔法卡效果改为适用于另一位玩家；`source_activation=spell_card_activation`、`recipient_rule=other_player`、`count=1` | 精灵之镜（35563539）改变魔法效果适用者 | 不取卡片对象；不同于改变魔法对象，不是无效或效果改写 |
| `redirect_spell_target` | 改变魔法卡的单张卡对象；记录 `source_activation=spell_card_activation`、`original_target_kind`（`monster`／`spell_trap`／`card`）、`new_target_rule=different_legal_target`、场上 `from_zones`、`count=1` | 天使的手镜（17653779）原对象为怪兽；恶魔的手镜（58607704）原对象为魔陷 | 新对象须满足原魔法条件，不能继续选原对象；不是改变适用玩家或继承原魔法能力 |
| `change_race` | 改变怪兽种族；记录非空种族标识 `race`、`from_zones`、`count`、`duration` 和布尔值 `applies_to_later_monsters` | 龙之血族（2833249）将处理时己方表侧怪兽变龙族，后出现者不适用 | `treat_as_name` 只改变卡名。已有 `etag:stat-change` 明确包含种族／属性，应继续使用，不另造 TAG |
| `activate_field_spell` | 在本效果处理中从来源区域发动场地魔法；记录 `from_zones`、`to_zones=['field_spell']`、`count=1`、`resolve_activation_effect=false` | 虚拟世界（89208725）的发动分支 | 仍须满足发动条件，但不另起连锁或进行该场地魔法的卡发动时处理；`place_field_spell` 仅表侧放置，不能代替；不继承场地魔法的检索能力 |
| `reveal_drawn_cards` | 在规定期间公开指定玩家将抽到的卡；记录 `player`、`duration` | 绒儿的读心术（58015506）公开对方此后抽到的卡 | 本卡不进行抽卡，不等于确认已在手卡的卡，不自动挂抽卡 TAG |
| `reverse_stat_modifiers` | 令攻守上升／下降效果反向；记录 `duration`、非空且不重复的 `stats`（`atk`／`def`） | 天邪鬼的诅咒（77622396）反向攻守增减 | 不反转设置原本数值的处理，不等于效果无效；使用既有 `etag:stat-change` |
| `reroll_dice` | 已适用效果允许以后重新掷骰；记录 `player`、`duration`、正整数 `applications`、`dice_scope=entire_dice_procedure`、`stacking`（`non_cumulative`／`cumulative`） | 反转骰子（83241722）本回合一次完整重掷，同类效果不累计 | 当前协议只表达完整掷骰流程，不能保留连续多次中某一次的结果；不产生新连锁，也不继承骰子结果决定的能力 |
| `move_to_end_phase` | 当前回合直接移行至结束阶段；须有 `phase=end` 与 `duration` | 闪光弹（9267769）直接攻击受伤后直接进入结束阶段 | 不进行被越过的主要阶段2；`end_battle_phase` 本身仍允许通常进入主要阶段2，不是相同动作 |

`phase` 取 `draw`／`standby`／`main1`／`battle`／`main2`／`end`。所有新动作的整数参数拒绝布尔值、字符串、负数及不符合上述下限的数值；上述 `count` 中只有移除指示物、卡顶放置、盖卡确认与种族改变允许 `all`。种族和指示物种类仍是须由逐卡官方资料核对的文本参数，不把任意字符串当作已验证裁定。

新增区域 `opponent_extra` 表示对方额外卡组。正例为《融合失败》（58392024）让对方融合怪兽回其额外卡组；反例为 `extra`（自己额外卡组）和 `opponent_extra_monster_zone`（场上的对方额外怪兽区域）。这三个区域不互作子区域，也不修改原有区域查询扩展。`opponent_deck_top` 已存在，本轮沿用，不重复登记。需要裁定补查的《成功确率0%》（6859683）不能仅因区域已登记就转为已核对。

### 发动对象的数量区间

`structure.targeting` 的旧 `count` 仍表示固定数量。新对象可以使用 `min_count` 与 `max_count` 表示区间，两字段必须同时存在；`min_count` 为非负整数，有限 `max_count` 必须为整数且 `min_count <= max_count`。`max_count: null` 明确表示没有固定上界，不能用缺省字段暗示无上界；不得同时提供 `count`。布尔值、负数、其他非整数、只给一端或反向区间均拒绝。区间最小值允许0仅是结构表达能力，不替具体卡片证明0对象可以发动。

第二组短卡文还使用以下受控动作，均由官方卡文及补足逐卡核对，不由名称或关键词推断：

| 动作 | 必填语义与示例 | 与相近能力的区别 |
| --- | --- | --- |
| `toss_coin` | `count` 为正整数，`executor` 指掷币玩家；结果用至少两个非空 `branches` 或 `then` 后续表达。圣杯A按表里决定哪一方抽2张 | 随机结果不同于玩家任意选择的 `choose_branch`；两方抽卡不能串用来源与去向 |
| `roll_dice` | `rolls` 为正整数，`faces=6`，`executor`、结果计算说明 `result` 及结果后续／分支。无差别崩坏按两次总和判断 | 不同于允许以后重掷的 `reroll_dice`；具体破坏另有独立处理项 |
| `add_to_extra_faceup` | 来源区域、正整数 `count`、`to_zones=['extra_faceup']`；可用布尔 `shuffle_source_after` 记录后续洗牌。灵摆宝藏从主卡组表侧加入额外 | 不属于检索、特殊召唤、送墓或返回主卡组 |
| `set_lp` | `recipient` 为 self／opponent／both，`amount` 为非负整数。生命转换将双方基本分设为3000 | 不视为伤害、回复或支付费用，不自动赋予这些 TAG |
| `replace_draw_with_discard` | `source_activation=draw_only_effect`，`quantity=cards_that_would_be_drawn`，`reveal_to=both`；`counts_as_draw=false`、`cards_enter_hand=false`；来源只可为卡组顶，去向只可为墓地 | 《无效》把原应抽的卡公开后直接丢去墓地；不是先抽卡再丢手卡，也不无效原效果 |
| `redirect_effect_damage` | `source_player`、`recipient`、`duration` 和 `source_effect`（activated／continuous／all）。自然反射只转移对方发动效果原本给予自己的伤害 | 不新建一份固定数值伤害，不覆盖战斗伤害；不继承原伤害来源的其他能力 |
| `place_deck_bottom` | 沿用 `place_deck_top` 的执行者、来源、数量、洗牌顺序参数，去向限定 deck_bottom／opponent_deck_bottom；沿用 `etag:deck-look` | 天地返将选定卡留在卡组最下面，不伪装成回卡组或卡顶放置 |

所有新整数参数均拒绝布尔值；随机处理必须保留结果如何决定后续的说明。任何一张卡的具体发动条件和例外仍由其标注与来源承担，不以受控动作校验代替规则判定。

正例：《火山充能》（33725271）应写 `{min_count: 1, max_count: 3, filter: '自己墓地火山怪兽'}`，不能保留 `count: 3` 或改成0至3。《起翼升阶魔法-急袭猛禽之力》（38044854）的2只以上写 `{min_count: 2, max_count: null, filter: '包含己方场上怪兽的自己场上／墓地RR超量怪兽'}`，不能编造上限。反例：《希望之光》（82529174）固定2只，继续使用 `count: 2`。能力事实和标注详情分别显示“1至3个”“至少2个”；查询不新增或改变数量求解规则，快照完整保留原对象结构。旧固定数量条目不迁移、不重绑卡文；本轮新动作与区域也不会自动重写旧标注。历史快照原有 `count` 展示保持；38044854旧 `count:2 + min_count:2 + variable_count:true` 混合描述须经来源复核迁移到显式无上界结构，不能继续作为新的有效内置条目。

### 03批新动作与动态对象数量

本批新增以下九个动作，不新增 TAG，也不从可选卡片的未来效果推导抽卡、破坏、回复或特召能力。每项仍须提供非空 `selector.text`。

| 动作 | 参数协议与正例 | 反例与兼容边界 |
| --- | --- | --- |
| `increase_pendulum_summon_limit` | `executor=self/opponent/both`、正整数 `count`、`from_zones`（`hand`／`extra_faceup`的明确集合）、`duration`。额外灵摆（58308221）本回合额外从表侧额外卡组进行1次P召唤 | 不在本效果结算中立即召唤，不等于 `special_summon` 或增加通常召唤次数；本卡实际不包含手卡来源 |
| `win_duel` | `recipient=self/opponent`、布尔值 `delayed`／`creates_chain`、非空 `resolution_timing`。若按回合计数，则正整数 `turn_count` 与布尔值 `count_both_players_turns`／`start_turn_inclusive` 三者必须成组出现。终焉的倒计时（95308449）从发动回合计第20个双方回合结束时胜利，不另起连锁 | 不等于给予致胜伤害，也不等于使基本分变0；不自动执行回合计数或胜负判定 |
| `place_and_use_spell` | `executor=self/opponent`、`count=1`、明确 `from_zones`、`to_zones`仅为 `spell`／`field_spell`、`used_spell_cost_timing=resolution`、`used_spell_targeting_timing=resolution`。二重魔法（24096228）使用对方墓地魔法，本体放入自己的正确卡区，其费用和对象在本效果处理时另行处理 | 不只是取得效果的 `copy_effect`，也不只限场地魔法；不能省略被使用魔法的条件、费用及对象，不能借未知魔法添加能力 TAG |
| `return_to_field` | `count`为正整数或`all`、`from_zones=['banished']`、场上 `to_zones`、非空 `position`／`resolution_timing`、布尔值 `delayed`、`creates_chain=false`、`counts_as_special_summon=false`。虫洞（22959079）下次自己准备阶段按回场规则返回 | 不属于从除外区特殊召唤；不从旧卡文推断额外怪兽区应回到哪个具体格子，正常放置条件仍交给规则判断 |
| `skip_turn` | `player=self/opponent/both`、正整数 `count`、非空 `duration`、`stacking=non_cumulative/cumulative`。忍之六武（6357341）跳过下次对方整个回合，多个适用于同一下次回合的效果不累加 | 不等于只跳过战斗阶段；不执行真实回合调度 |
| `swap_lp` | `players`必须各含一次`self`和`opponent`。大逆转谜题（5990062）在条件满足时交换双方当前基本分 | 不是效果伤害、回复或支付基本分，不借此赋予这些TAG |
| `change_attribute` | 明确`from_zones`、正整数或`all`的`count`、非空`duration`、`attribute_selection=activation/resolution/fixed`；固定属性时登记`attribute=earth/water/fire/wind/light/dark/divine`，选择属性时不同时写固定值。炼金生物 人工生命体（40410110）在处理时选择属性 | 使用既有`etag:stat-change`的属性语义；不改种族、不冒充攻击力处理 |
| `change_equip_target` | 场上`from_zones`、正整数或`all`的`count`、`keeps_controller=true`，禁止`to_zones`。力之集约（7565547）把场上能合法装备的既有装备卡改装给对象 | 保持装备卡控制权；不是新发动装备卡、放置卡片或取得控制权，不能省略装备关系的合法条件 |
| `shuffle_deck` | `executor=self/opponent/both`、`from_zones`只能为明确的`deck`／`opponent_deck`，不使用`to_zones`或指定张数；若含`count`只能为`all`。恶魔的智慧（28725004）洗切自己整副卡组 | 使用既有`etag:deck-look`的卡组操作语义，不赋予查看卡组、抽卡或回卡组能力 |

依据为各卡 [KONAMI OCG补足：额外灵摆](https://www.db.yugioh-card.com/yugiohdb/faq_search.action?cid=17163&ope=4&request_locale=ja)、[终焉的倒计时](https://www.db.yugioh-card.com/yugiohdb/faq_search.action?cid=5788&ope=4&request_locale=ja)、[二重魔法](https://www.db.yugioh-card.com/yugiohdb/faq_search.action?cid=5629&ope=4&request_locale=ja)、[虫洞](https://www.db.yugioh-card.com/yugiohdb/faq_search.action?cid=5132&ope=4&request_locale=ja)。这些类型及参数描述静态处理，不实现真实时点调度、额外召唤执行或自动宣告胜利。

`structure.targeting[].count_rule` 表示必须在发动时按卡文计算的对象数量，不能与同一对象项的 `count`、`min_count` 或 `max_count` 同时出现。该对象必须含 `mode`、非空 `text`（计算依据）及 `evaluated_at: 'activation'`，且不接纳其他未定义键：

- `mode: 'exact'`：恰好选择计算得到的N个对象，禁止 `minimum`。正例《零日冲击波》（93014827）按作为费用解放的暗属性连接怪兽的连接标记数量取恰好N张对象，不是最多N张。
- `mode: 'up_to'`：以上述计算结果N为上限，必须给非负整数 `minimum`，排除布尔值。正例《对星遗物的抵抗》（58374719）以发动时双方相互连接怪兽数量为上限、至少选1张魔陷。处理时怪兽数量改变不重新选择对象。

数量依据只作为文字显示，不解析为表达式、不读取当前局面求值，也不证明该局面有足够合法对象。能力事实和详情分别显示“动态固定：N个，N＝…（发动时确定）”与“动态上限：minimum至N个，N＝…（发动时确定）”。常量数量继续使用固定 `count`、常量闭区间或显式 `max_count:null` 的开放上界；不能用无上界隐藏动态上限，也不能把计算得到的最大值误标为固定数量。原有查询的同处理项动作／区域绑定及固定获赋效果匹配不改变；旧快照不重新求值或改写。

行动限制仍保留`etag:lock`，具体处理项可用布尔值`self_only=true`表示仅自身的负面限制，或`summon_response_only=true`表示仅本次召唤成功的响应窗口。它们可按限制TAG检索，但不能因此推导持续终场干扰或手坑用途；同一效果的独立无效或除去能力仍可生成用途候选。未带这些字段的历史条目保留原行为，不通过新字段推断或改写历史快照。

本轮怪兽批次的攻守变化、保护、限制与战斗伤害变化须保留对应既有TAG。34张漏标已补齐，并逐张保存TAG单独筛选及TAG与动作组合的68条真实查询回归；仅增加这些已审核处理的标签，不通过卡文关键词生成规则。完整逐卡与来源绑定见[本轮清单](card-annotation-batch-2026-09-26-short2.json)。

## 5. 审核状态与来源追溯

### 怪兽02批的攻击手续与伤害性质

`actions.require_attack_return`表达《霞之谷的猎鹰》（82199284）攻击宣言的回手手续：`from_zones`为场上范围，`to_zones`为`hand`／`opponent_hand`的明确集合、`count=1`、`executor=self`、`exclude_source_instance=true`、`payment_timing=attack_declaration`及`is_effect_movement=false`。须实际回到持有者手卡，不能选本卡实例、衍生物或回额外卡组的怪兽。它不是`return_hand`处理，也不是效果发动的费用，不产生`etag:add-hand`；已有本批资料不改写为效果回手。[官方补足](https://www.db.yugioh-card.com/yugiohdb/faq_search.action?cid=8109&ope=4&request_locale=ja)和关联FAQ支持攻击手续与被效果回手的区别。

`actions.convert_battle_damage`表达《守墓的从者》（99690140）将本卡原应给对方的战斗伤害视为效果伤害：`from_zones=['monster']`、`count=1`、`source_damage=battle`、`result_damage=effect`、`damage_source=this_card`、`recipient=opponent`、`creates_chain=false`，禁止固定`amount`和卡片`to_zones`。保留`etag:effect-damage`与`etag:damage-modify`，但不会命中固定烧血`burn`动作，不赋予追加伤害或战斗破坏以外的效果破坏。怪兽仍正常按战斗破坏处理。[官方补足](https://www.db.yugioh-card.com/yugiohdb/faq_search.action?cid=5513&ope=4&request_locale=ja)明确永续适用与伤害性质。

伤害承受者由事件确定时可在处理项以`recipient_rule`保存完整规则，不能同时编造固定`recipient`。本批《原子萤火虫》（87340664）给予战斗破坏它的玩家1000伤害；本体控制权变化后不能简单固定为墓地效果发动者的对方。此字段仅是规则说明，不执行局面计算。

1.47.3 增加直接处理与 TAG 一致性检查：对加入手卡、抽卡、回卡组、确认手卡／卡组、破坏、除外、送墓、召唤、无效、效果伤害和回复的明确处理递归核对标签，包括分支与后续处理；不会从关键词自动生成已核对数据。规则段、数值变更和行动限制可能在其他结构字段表达，不套用这项一一对应规则。已核对的诱发即时效果、陷阱发动及速攻魔法发动必须使用正确的 `fast_effect`；带条件的起动／快速时点转换仍保留其条件，不按整个文件统一替换。

新增区域 `field_spell` 表示场地区，正例为《访问码语者》②可破坏对方场地区的卡，反例为只能处理怪兽的效果。该效果显式列出 `opponent_monster/spell/pendulum/field_spell`，适用者仍由选择器说明限定为对方。查询 `field` 可命中明确登记的这些场上子区域；`monster` 包含 `opponent_monster`，`spell` 包含 `pendulum`。仅写 `field` 时不会推断为能处理魔陷或其他特定子区域。此规则仅扩展区域筛选，不判断局面合法性，也不改变默认「同一效果」查询的分支能力边界。

个人文件支持旧 `version=1` 的只读兼容，新保存为 `version=2`。每张卡的个人覆盖层记录 `text_digest` 与 `frozen_text`，另有 `history[]` 保留旧覆盖层。版本不匹配或旧记录没有指纹时，当前效果不合入旧 TAG、备注与确认标记，并提示待核对；旧卡文详情仅能显示与其冻结指纹相同的旧个人资料，且仍不参与能力查询。浏览不重写文件；首次重新保存时先备份完整原文件，再归档旧覆盖层和原备注，并绑定新卡文。历史内容可在详情中查看，需要的修正须重新添加并核对；不提供跨卡文的自动重挂。写盘失败时内存与原文件均保留，自动草稿的指纹机制保持独立。旧版程序不识别 `version=2`；如需回退程序，先另行保留新版个人文件，再恢复升级前的 `backups/annotations/<revision>.json`，不能直接让旧程序读取新版文件。

- 三个来源层级严格区分：**自动生成**（`origin=auto`，自动草稿，永不计入已核对）、**人工核对**（`manual`，内置资料按卡文逐字核对）、**脚本映射依据**（历史 `engine`，效果编号与脚本映射沿用 `AUDITED_EFFECTS`，要求卡文指纹一致；不代表全部处理、裁定或当前可发动性已通过引擎验收）。
- 每个内置条目记录 `checked_on`、`basis` 与卡文指纹；内置资料文件头记录核对时的卡库 sha256（`verified_against`）。运行时另附当前 `Catalog.sources` 的逐库 sha256。
- 个人修正存于 `<runtime>/_trainer/card-annotations.json`（`revision` 乐观锁、原子写入、每次保存前备份到 `backups/annotations/<revision>.json`）：核对状态翻转、效果备注、效果 TAG 增删（对内置标签的增删记为个人覆盖，可撤销）。人工内容在卡库更新时保留。
- 冲突提示：卡文指纹失配 → `stale`，旧标注冻结展示并提示复核；同版重复导入不重复写入。

## 6. 组合查询语义（`op: query`）

- 条件分两层：卡片层（关键词、类型、标签库 TAG、状态）与效果层（效果 TAG 多选 any/all、动作、来源区域、去向区域、次数限制、费用、发动时点）。
- **默认范围 `scope=effect`**：所有效果层条件必须在**同一效果**内成立；同一张卡的不同效果不串用条件。
- 动作、来源区域、去向区域构成一组处理条件，必须由同一个处理项满足；会遍历顺序后续与分支，但不从其他处理项借用区域。例如封印之黄金柜先从卡组除外、以后从除外状态加手，不能命中 `action=add_hand + from_zone=deck`。
- `scope=card`：允许 TAG、次数、费用、时点等条件由不同效果分别满足，但动作与来源／去向组合仍保持上述同一处理项约束。每个条件须指出由哪个效果命中；确需跨效果时结果明确标注「跨效果命中」。
- 每个命中给出依据：条件名、取值、依据文案（TAG 定义／处理项选择器／隐含去向等）、效果原文与编号、状态与来源；`to_zone` 未显式标注时按动作隐含去向匹配并注明「隐含去向」。
- 查询只在已标注范围内进行，结果同时给出 `annotated_total` 与 `catalog_total`：**未标注卡片不代表没有该能力**。
- `actions.choose_branch` 明确把同一效果中的多个处理标成互斥选项；当前组合查询仍只保证条件在同一效果内，不求解是否位于同一分支，故多个 TAG 同时命中不能解释为一次发动会同时执行各分支。

## 7. 更新与复核流程

- 卡库或超先行补丁更新后 `Store.reload_resources()` 会重建 `Catalog` 并 `CardAnnotations.reload()`：指纹一致的标注照常；失配的转 `stale` 冻结；个人备注与核对标记保留；内置资料中已不在卡库的卡列入 `missing_codes`。
- 恢复能力：内置资料随版本管理（Git 历史）；个人层每次保存留有 revision 备份。
- 新卡标注的增量流程：先 `op: draft` 生成自动候选（明确 auto 状态）→ 人工按 §3 结构补全内置资料并运行交接指南中的校验器 → 审核入库。界面仅维护个人备注、标签覆盖和对完整人工标注的确认，不是完整结构编辑器。

## 8. 与其他模块的复用关系

- 卡片身份、卡库加载与来源 sha256 复用 `Catalog`；效果编号映射复用 `card_semantics.AUDITED_EFFECTS` 与其分句规则；原子写入、revision 锁与备份沿用 `plan_library`／TAG 库的既有机制。
- 1.48.0 通过统一只读能力服务接入卡片详情、三类标记、构筑与 TAG 检索、起手分析、断点与实战参考。引用按卡号＋效果键＋卡文指纹定位；1.49.0 进一步自动重建旧用途库、用途 TAG 和起手角色，旧个人用途覆盖备份后替换；原有规则判定和录制历史仍保留，详见[跨模块能力引用](card-capability-integration.md)。

## 9. 当前状态与后续阶段

- **已完成**：规范与实现（分段、校验、覆盖清单、组合查询、自动草稿、个人层）、20 个当前 TAG 与 1 个兼容标签的词表；首批 11 张样本、第二批 35 张引擎审计清单、第三批 62 张手坑／解场，以及后续五次完整系列阶段新增 100、94、100、96、97 张。第八批卫星闪灵／铁兽／龙辉巧／随风旅鸟／十二兽／朋克的来源和异画核对见[逐卡清单](card-annotation-batch-2026-09-25-phase5.csv)，上一批见[1.47.7 清单](card-annotation-batch-2026-09-25-phase4.csv)。
- **进行中／未完成**：全卡库逐卡逐效果标注（当前 14,716 张非衍生物中，1,502 张已标注，13,214 张尚未标注），继续以完整系列分阶段核对；完整用途覆盖与动态局面推断仍不由静态标注承担。样本之外的任何能力查询结果均受「已标注范围」限制，不宣称全库准确。

## 10. 1.46.0 复核与兼容要求

- `frozen_text` 保存与 `text_digest` 一致的本地卡文快照。卡文失配时按旧快照展示旧标注，并单列当前原文；旧资料没有快照时明确提示缺失，绝不把新卡文同序号套在旧结构上。
- `sources[]` 保存稳定来源 id、标题、HTTPS URL、`checked_on` 与 OCG/TCG 口径；备注 `source_refs` 指向此表。卡库名称用于显示，卡号用于身份，官方 `cid` 是来源身份，三者不混用。
- `effect_type` 来自新增受控词表，区分起动、诱发、诱发即时、永续、魔法／陷阱卡发动、陷阱效果、灵摆效果与非效果文本。`kind` 仍仅表示分段形式；没有编号不能据此判成非效果。
- `usage_limits` 的旧 `name_soft_opt` 等键仅为兼容名称；同名次数限制不得因键里有 soft 一词而理解为单卡限制。按原文区分「使用」与「发动」，已有标签 ID 不改名。
- 总库数包含衍生物；可标注数与七种状态统计排除衍生物。详情与筛选中的 `partial` 保持一致。`catalog_scope=all` 可浏览未标注卡；无能力条件时无效果卡也可命中。
- 「跨效果命中」只在整卡查询确实需要不同效果满足条件时显示；普通多效果展示不显示。动作与区域按同一处理项匹配；TAG、费用、次数、时点仍属于效果层，不证明同一分支同时可执行。仅选 TAG 与区域、未选动作时，也不把 TAG 自动绑定到某个处理动作。
- 改正了墓指的盖放前提、泡影纵列处理前提、提示员的处理后自锁、自奏圣乐之阶的整回合限制、旋钮手召唤对象与二选一、托马斯的 DDD 子系列与对方全体战斗伤害减半范围。
- 官方规则链接、分类范例与后续智能体的具体交付要求见[标注交接指南](card-annotation-agent-guide.md)。静态参考样本并非穷尽所有特殊裁定。

## 系列浏览与视觉标识（1.47.1）

默认进入紧凑系列卡牌夹（每页 48 个、高度 92px），按系列最早已知的 OCG／TCG 实体卡发售日期降序排列；可切换日期升序和中文名称。相同日期用 `Intl.Collator('zh-Hans-CN')` 的中文名稳定排序，未知日期始终置后，无系列归属最后。日期基于全系列成员，不能因筛选只剩某张新卡而改变系列首发日期。`card-release-dates.json` 为离线公共日期快照，`card_release_dates.py` 负责明确卡号映射和首发计算；来源与更新见[制作流程](card-series-production-guide.md)。

全卡库浏览包含未标注卡；进入系列后仍沿用每页 30 张的查询，列表每张卡左边显示 46×66px 缩略图。筛选整体默认收起；详情右上角「查看卡图」点击后才加载原图，并在点击位置附近打开原生 Popover，边缘位置向内调整。重复点击、外部点击、Esc、关闭按钮、滚动、窗口尺寸变化或详情更换均可收起；原图不再把正文推开。彩色效果 TAG 同时保留中文名称、分类分组和选择勾号。额外卡组标志严格读取融合／同调／超量／连接类型位；仪式、灵摆、调整另行显示，不因灵摆类型而直接视为额外卡组怪兽。

`card_series.py` 从当前卡库 64 位 `setcode`（四个 16 位编号）和内置系列表建立只读成员索引，保留父／子系列和多系列，兄弟子系列不互相混入；不以卡名包含、卡文提及、关联推荐或个人 TAG 手动成员推导系列归属。编号非零但没有译名的卡进入「未命名系列 · 0x…」，只有没有系列编号的卡进入「无系列归属」。后者表示当前卡库未登记，不是完整规则裁定。

`annotation-series.json` 保存二十套徽记、官方系列名及三十五张代表卡来源。普通系列保留本地译名；官方名覆盖只作用于标注展示，旧译名保留为检索别名。系列徽记可随归属应用到全系列，但详情单独区分「代表样本已核对」「来自卡库」「类型或编号变化」。效果标注核对状态和个人数据不变。封面复用 `/pics/<code>.jpg`，没有资源时沿用应用卡背，加载失败保留目录图形。制作与扩充见[交接流程](card-series-production-guide.md)。

`POST /api/annotations` 的 `query` 新增 `group_by: "series"` 返回 `{total, folders}`，`total` 为去重卡片数，文件夹计数可能因多系列而重复；各夹计数与封面基于当前全部筛选条件。`series: "set:…"` 或 `"unassigned"` 限定目录，个人 TAG 筛选仍独立叠加。卡片结果和详情中的 `series[]` 提供名称、徽记、名称依据、代表样例状态与官方来源。资源重载会重建成员索引。
