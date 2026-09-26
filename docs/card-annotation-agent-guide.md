# 卡片标注交接指南

适用版本：1.49.6。供后续智能体在现有 2,488 张内置效果参考样本上继续扩充，最新覆盖以[进度账本](card-annotation-progress.md)和实际资料为准。先读项目 `AGENTS.md` 与[体系规范](card-annotation-system.md)；旧优先清单已完成，现作为历史记录保留在[补卡提示词](card-annotation-next-batch.md)。只维护静态卡片知识，不启动已封存的 AI 学习计划。系列中文名、徽记与封面是独立展示资料，按[系列标识制作流程](card-series-production-guide.md)补充，不把系列样例核对计入完整效果标注数量。

2026-09-26用户确认改用[统一批次工具与续接流程](card-annotation-pipeline.md)：固定完整清单，机械准备并行，逐卡语义审核保留；每约20张检查，纯数据且机制稳定的完整发布阶段约300～500张统一测试、打包与审核发布。来源、词表或代码变化使检查缓存失效，合并前强制完整复查。新批次优先使用该工具，避免重复编写读取、分段和合并脚本；尚未审核的模板不得计入完成数量。

## 文件与交付范围

| 文件 | 用途 |
| --- | --- |
| `src/trainer/card-annotations.json` | 卡号、冻结卡文、效果结构、关系与来源 |
| `src/trainer/annotation-tags.json` | 通用标签、定义、受控词表 |
| `src/trainer/card_annotations.py` | 分段、校验、查询、个人覆盖层 |
| `scripts/check_card_annotations.py` | 只读检查来源、指纹、类型、分段覆盖 |

修改内置资料时保留旧条目与稳定 ID，不写用户运行目录、不覆盖个人标签、备注、牌组或备份。界面的「个人修正」只支持标签、备注与审核标记，不能代替完整结构标注。

个人修正已按卡文指纹隔离；旧版本或指纹未知的资料保留在历史中，不得为了消除待核对状态把旧记录直接绑定到新卡文。当前校验器增加效果类别／快速标志、直接处理／TAG 一致性检查；失败时核对证据并修正资料，不能删掉校验来通过。条件分支、对方执行及阶段延迟的明确处理同样要记录相应 TAG，但 TAG 不代表一次发动可同时执行所有分支。

## 每批工作步骤

1. 明确本批卡号清单，按实际卡库读取 `name/type/desc`。数字卡号是身份；卡名译法、官方数据库 `cid`、系列 `set:` 编号是不同概念。
2. 查询 KONAMI 官方 OCG 卡文及补充说明，记录来源 URL、规则地区和核对日期。禁止拿官方站内的用户牌组评论当作裁定。仅有 TCG 来源时明确差异，不能直接推定 OCG 处理。
3. 保留本地完整卡文为 `frozen_text`，用 `card_annotations.digest()` 计算指纹；分段必须使用 `segments(desc,type)`，不能手写效果编号映射。灵摆文本 `p*` 与怪兽文本 `m*` 分开。
4. 逐段判断 `effect_type`。无编号段可能是效果、规则、次数约束、召唤手续或描述文本，不能只凭是否有①来分类。通常怪兽的描述不会因为出现“破坏”等词就成为效果。
5. 分开记录发动条件、区域、费用、对象、处理、次数、持续时间、分支与限制。事实无法确定时保留待核对项，不能靠关键词猜测后标成已核对。只有骨架或缺段的条目保持 `draft`／部分标注。
6. 通用标签表达共性处理；具体区域、对象、适用者与前提放入结构。新增受控取值必须先给出定义与正反例，再检查已有标签是否已覆盖。
7. 每张卡填 `sources[]`，备注 `source_refs` 引用其 id；新参考样本需要保留快照和来源。`review.origin=manual` 表示人工资料核对；自动产生的初稿保持 `auto`。已有 `engine` 字段仅为脚本映射，不能用来宣称完整规则已验证。
8. 运行下面的检查，复查本批差异、README 与隐私范围，依项目规则提交和推送。交付本批卡号、修正项、来源、检查结果、未解决的裁定问题；不扩大宣称全卡库完成度。

```powershell
python scripts/check_card_annotations.py --runtime .local/YGOPro-Lite
python scripts/check_annotation_series.py --runtime .local/YGOPro-Lite
python -m unittest discover -s tests -p test_card_annotations.py -q
node --test tests/card_annotations_view.test.cjs
```

若实际卡库在其他位置，使用含 `cards.cdb` 的真实目录。省略 `--runtime` 只检查资料内部一致性，不能作为当前卡库卡文一致的证据。发生卡文变化时先核对新文本和全部受影响段落，不能仅替换指纹来消除警告。界面或行为有变化时另运行后台 Electron 验收。

## 分类边界

页面的八组分类与英文结构键属于本项目的受控词表；官方来源用于核对卡文和规则，不表示 KONAMI 采用了相同的标签体系。

| 容易混淆的内容 | 标注方式 |
| --- | --- |
| 效果送墓、破坏与送墓费用 | 只有直接的效果处理挂能力标签；费用进入 `cost`，不能从破坏、解放或素材行为推导送墓能力 |
| 检索、回收与弹回手卡 | 共享加入手卡标签，分别记录卡组、墓地、场上等来源；抽卡用独立标签 |
| 发动无效与效果无效 | 分开；“无效并破坏”不能单凭结果判断无效的是发动还是效果 |
| 对手干扰与己方负面效果 | 标签描述处理，不直接等于战术用途；明确被影响者，例如托马斯会无效自己特召出的怪兽 |
| 自锁与对手封锁 | 行动限制独立分组，记录适用者、开始时点、结束时点、是否回溯本回合以及无效后的处理 |
| 素材规则与特召效果 | 手卡调整作为同调素材的手续属于非效果文本，不是一次可发动的特召能力 |
| 使用次数与发动次数 | 按原文分别记录；`name_soft_opt` 等旧键保留兼容，不应照英文字面推定规则 |
| 诱发效果与快速效果 | 诱发效果可能在对方回合触发，但不因此成为诱发即时效果；`fast_effect` 不是“对方回合可任意发动” |
| 二选一与顺序处理 | `branch` 表示互斥分支；`then` 表示后续；`condition`、`optional`、`duration`、`position` 都应保留 |
| 无标注与无效果 | 缺少标签只表示未知；明确无效果才写 `no_effect=true`。衍生物不进入标注覆盖基数 |

旧 `etag:burn` 将伤害与回复合在一起，仅为个人旧数据兼容。新标注分别用 `etag:effect-damage`、`etag:recover-lp`。旧费用取值 `material_as_cost` 不用于新资料，素材手续应独立处理。

默认查询要求条件在同一效果内成立，并把动作与来源／去向绑定到同一个处理项。例如封印之黄金柜“从卡组除外、以后从除外加手”不能当作“从卡组加手”。TAG、费用、次数、时点仍按效果层检查；未求解同一分支能否同时执行全部条件。查到旋钮手②同时含回卡组与检索，并不意味着二选一能同时执行。只有 TAG 和区域、未选动作时，不把 TAG 自动绑定为某个动作。静态标签不能给出当前局面可发动结论。

## 已联网复核的参考样本

下表为 2026-09-24 的参考索引。完整文本沿用本地快照；此处仅概括分类差异。

| 本地卡号与名称 | 参考重点与官方来源 |
| --- | --- |
| 14558127 灰流丽 | 丢弃自身是费用；无效的是效果，三个项目是响应条件。[官方说明](https://www.db.yugioh-card.com/yugiohdb/faq_search.action?cid=12950&ope=4&request_locale=ja) |
| 10045474 无限泡影 | 手发条件是非效果文本；纵列处理还要求成功无效、此前盖放且本卡仍在魔陷区。[官方说明](https://www.db.yugioh-card.com/yugiohdb/faq_search.action?cid=13631&ope=4&request_locale=ja) |
| 24224830 墓穴的指名者 | 成功除外后才适用相应无效；区分怪兽效果与作为魔陷适用的效果。[官方说明](https://www.db.yugioh-card.com/yugiohdb/faq_search.action?cid=13619&ope=4&request_locale=ja) |
| 16387555 杀手级调整曲·提示员 | 素材手续不是效果；调整自锁从未被无效的处理后开始，不追溯此前特召；②除外与放回同时处理。[官方说明](https://www.db.yugioh-card.com/yugiohdb/faq_search.action?cid=21956&ope=4&request_locale=ja) |
| 17209452 杀手级调整曲·旋钮手 | ①的召唤不限于展示的调整；②发动时选择一个分支，手卡确认成功后才能追加检索。[官方说明](https://www.db.yugioh-card.com/yugiohdb/faq_search.action?cid=22531&ope=4&request_locale=ja) |
| 16509007 杀手级调整曲·混音手 | 卡组与墓地是两种检索来源；②对象破坏与素材手续分别记录。[官方说明](https://www.db.yugioh-card.com/yugiohdb/faq_search.action?cid=21953&ope=4&request_locale=ja) |
| 703897 自奏圣乐之阶 | ①对应魔陷卡发动与怪兽效果；②自锁涉及整回合，与提示员不同。[官方说明](https://www.db.yugioh-card.com/yugiohdb/faq_search.action?cid=14324&ope=4&request_locale=ja) |
| 41546 DD 魔导贤者 托马斯 | 灵摆与怪兽两块独立次数；破坏为处理；DDD 使用子系列；减半影响对方本回合全部战斗伤害。[官方说明](https://www.db.yugioh-card.com/yugiohdb/faq_search.action?cid=12409&ope=4&request_locale=ja) |
| 213326 E-紧急呼唤 | 卡组检索，无费用；与墓地回收按区域区分。[官方卡文](https://www.db.yugioh-card.com/yugiohdb/card_search.action?cid=6672&ope=2&request_locale=ja) |
| 674561 暗黑爆发 | 墓地对象回收，需要属性与攻击力条件。[官方卡文](https://www.db.yugioh-card.com/yugiohdb/card_search.action?cid=7453&ope=2&request_locale=ja) |
| 89631139 青眼白龙 | 通常怪兽描述，不生成效果标签。[官方卡文](https://www.db.yugioh-card.com/yugiohdb/card_search.action?cid=4007&ope=2&request_locale=ja) |

速攻魔法的通用盖放规则另参照[官方规则书](https://www.yugioh-card.com/ygo_cms/ygo/all/uploads/Rulebook_v9_en.pdf)：对方回合通常须此前盖放，盖放当回合不能发动。具体例外仍需单卡依据。上述条目只作为已核对样本，未穷尽全部个别裁定，也不包含当前禁限卡表判断。

## 2026-09-24 第二批：引擎审计清单 35 张

上表 11 张之外，同日按缺口分析的首批建议补全 `card_semantics.AUDITED_EFFECTS` 中其余 35 张（卡文指纹与卡库一致，`engine` 字段由运行时自动挂接）。逐卡以官方 FAQ 页（`faq_search.action?cid=…&ope=4`）的卡文与「補足情報」为效果类别依据：官方明确写「いずれにも分類されない効果」的段落标 `no_chain_effect`（区别于官方明确「効果として扱いません」的召唤手续与次数文本）；从墓地发动的魔法效果标 `spell_effect`。覆盖：转生炎兽 9、相剑 3、杀手级调整曲 3、青眼系 3、白骨 2、死狱乡 2、黄金国 2、疾行机人 2，以及连接栗子球、救祓少女·米迦埃莉丝、冰剑龙 幻冰龙、齐唱僵尸、影灵衣的万华镜、机壳工具 丑恶、No.75 惑乱之风言暗影、虹光之宣告者、鲜花女男爵各 1。新增受控取值（七个）的定义与正反例见[体系规范 §4](card-annotation-system.md)。仍待逐条消化的个别裁定：白骨王子②在手卡或卡组缺其中一只时的部分处理细节未在官方补充说明中单列，结构按原文整段记录。

## 2026-09-24 第三批：手坑／解场 staples 62 张

按缺口分析建议②补全 `staples.json` 64 张中除灰流丽、无限泡影（首批已核对）外的全部 62 张（研究快照 `.local/anno-batch3-research/`，构建脚本 `.local/anno-batch3-*.py`）。逐卡以官方 FAQ 页「補足情報」为效果类别与处理时序依据；Dominus 四张与颉颃胜负按官方裁定区分为「盖放发动的通常陷阱＋非效果的手卡发动权」，坏兽①②③与深渊之兽①按「不属于四类（不产生连锁块）／条件性诱发即时」裁定标注。新增受控取值（三个：`actions.set_position`、`actions.take_control`、`cost_kinds.remove_counter`）的定义与正反例见[体系规范 §4](card-annotation-system.md)。仍待逐条消化的个别裁定：闭锁世界的冥神①「效果无效化」卡文未写结束时点，官方补充说明未单列持续时间，结构按无时限记录并保留待核对标记；接触的G②的素材封锁、超量素材等特殊离场情形未在官方补充说明中展开。

## 2026-09-25 第四批：完整系列与实战辅助 100 张

先按[候选与交付清单](card-annotation-batch-2026-09-25.csv)核对当前卡库 `name/type/desc` 与 108 张旧条目，最终新增杀手旋律／杀手级调整曲 8、旧文档四张辅助卡 4、相剑 14、驱魔姐妹 18、转生炎兽 39、天威 17 张；原有 19 张同系列条目复核后跳过，五个系列在这份卡库中的成员均已覆盖。包含两张无效果天威连接怪兽的素材规则和三张独立异画卡号；基础卡号和异画卡号保持独立，官方 cid 仅供来源追溯。

每张新增条目引用 KONAMI 官方 OCG 卡片页及 FAQ，卡文和补足情報原始页面保留在 `.local/anno-batch4-research/`；原有 19 张的当期复核快照在其 `existing/` 子目录。按约 20 张完成一次实际 runtime 校验、全段与来源审查，并运行 `python scripts/check_annotation_batch4.py --runtime .local/YGOPro-Lite --expected 100 --require-snapshots` 核对本机来源快照及费用／处理、发动／效果无效、互斥分支和来源区域的正反查询。换机没有本地快照时可省略 `--require-snapshots` 做其他只读回归，但不能声称重新完成来源复核。`actions.choose_branch` 表示互斥结构，现有查询仍只保证同一效果，不证明同一分支可同时满足多个条件。词表新增值的定义与反例见[体系规范 §4](card-annotation-system.md)，整轮验证见[1.47.4 记录](verification-1.47.4.md)。

## 2026-09-25 第五批：烙印、死狱乡、自奏圣乐、青眼 94 张

用户要求把当前卡库所有未标注卡分阶段处理。本阶段先建立[100 个本地卡号的候选及交付清单](card-annotation-batch-2026-09-25-phase2.csv)：四个完整系列合计新增 94 张，原有 6 张复核后保留。青眼白龙、青眼究极龙等本地异画卡号保持独立；无法直接由辅助映射查到 cid 的 17 个卡号，先逐个比对同名、同 `type`、同完整卡文指纹的基础卡，再以官方 OCG 卡页和 FAQ 核对。21 张新条目明确无怪兽效果，保存通常怪兽描述或融合素材文本，不生成机械效果 TAG。

每张新卡的官方页面快照在 `.local/anno-batch5-research/`，原有 6 张的当期复核快照在 `existing/`；来源快照仅本地保留。累计 20／40／60／80／94 张时以实际 runtime 校验并运行 `python scripts/check_annotation_batch5.py --runtime .local/YGOPro-Lite --expected 94 --require-snapshots` 的逐卡来源、完整分段和关键机制正反查询。新增受控动作 `place_faceup_card`、`modify_activation_window`、`allow_direct_attack` 与 `require_attack_payment` 的定义和反例见[体系规范 §4](card-annotation-system.md)。详细结果见[1.47.5 验证记录](verification-1.47.5.md)。

## 2026-09-25 第六批：影灵衣、召唤兽、珠泪哀歌族、神碑、白森林、星杯 100 张

先从当前 `Catalog` 和 `CardSeries` 重算，保存[101 个系列成员的候选及交付清单](card-annotation-batch-2026-09-25-phase3.csv)：新标 100 张、已有《影灵衣的万华镜》复核后跳过。六系列在当前卡库均达到全员覆盖；四个本地异画编号在姓名、类型、完整卡文指纹与基础卡一致后才共用官方 cid，但各自保留整数卡号。每张新卡的 OCG 卡页和 FAQ 原始 HTML 在 `.local/anno-batch6-research/`，原有条目的当期复核在 `existing/`，只本地保留。

累计 20／40／60／80／100 张时以实际 runtime 跑标注、系列和 `python scripts/check_annotation_batch6.py --runtime .local/YGOPro-Lite --expected 100 --require-snapshots`，后者逐条检查来源、快照、完整卡文指纹／分段以及关键机制查询正反例。官方补足情報给出明确效果类别的 145 个怪兽编号效果与结构分类交叉核对，未见不一致。星杯三张通常怪兽的 FAQ 没有补足条目，依据官方卡片页完整描述显式标为 `no_effect`，不推断效果。新受控动作及额外怪兽区域查询的定义与反例见[体系规范 §4](card-annotation-system.md)，测试范围见[1.47.6 验证记录](verification-1.47.6.md)。

## 2026-09-25 第七批：闪刀、半龙女仆、斩机、军贯 96 张

先从当前 `Catalog` 和 `CardSeries` 重算，保存[96 个本地卡号的候选及交付清单](card-annotation-batch-2026-09-25-phase4.csv)，四个完整系列此前均无内置效果标注。81 个官方 cid 对应 96 个本地卡号；14 个异画本地编号只有在同名、同类型、同完整卡文指纹确认后才共享官方 cid，仍逐号保留条目。官方 OCG 卡页与 FAQ 原始 HTML 仅保留 `.local/anno-batch7-research/`，不上传。

累计 20／40／60／80／96 张时用实际 runtime 运行标注与系列校验、`python scripts/check_annotation_batch7.py --runtime .local/YGOPro-Lite --expected 96 --require-snapshots`，核对官方快照、原文指纹、全部分段以及费用／处理、同调／超量素材、对方支付基本分／效果伤害等正反查询。官方 FAQ 明确分类的 128 个编号怪兽效果与标注类别交叉核对，未见不一致；通常怪兽《舍利军贯》保留完整文案并显式标 `no_effect`。本批核对中修正了光／暗连接素材组合、魔法卡发动与表侧效果发动的区分、可选展示的发动手续、控制权移交及对方支付基本分；旧 402 条不改动。受控取值的正反例及兼容说明见[体系规范 §4](card-annotation-system.md)，完整验收见[1.47.7 验证记录](verification-1.47.7.md)。

## 2026-09-25 第八批：卫星闪灵、铁兽、龙辉巧、随风旅鸟、十二兽、朋克 97 张

先从当前 `Catalog` 与 `CardSeries` 重算，保存[97 个本地整数卡号的候选及最终清单](card-annotation-batch-2026-09-25-phase5.csv)；六系列原先均无内置效果标注。97 个编号对应 95 个官方 cid；两张本地异画在同名、同类型、同完整卡文指纹核对后映射官方 cid，但分别保留本地条目。官方 OCG 卡页及 FAQ 原始 HTML 仅在 `.local/anno-batch8-research/`，不进入 Git 或安装包。

累计 20／40／60／80／97 张时用实际 runtime 运行标注与系列校验，执行 `python scripts/check_annotation_batch8.py --runtime .local/YGOPro-Lite --expected 97 --require-snapshots` 核对快照、指纹、全分段、费用与处理、召唤／效果无效、仪式和超量素材、回合自锁及互斥分支的正反查询。官方 FAQ 明确分类的 138 个编号怪兽效果与结构类别交叉核对，未见不一致。旧 498 条逐项保留；新增值的定义、正反例和兼容说明见[体系规范 §4](card-annotation-system.md)。本批只修改内置资料和校验，不操作真实用户数据；后续版本的跨模块能力读取与本批静态资料的边界见[1.49.1 验证记录](verification-1.49.1.md)。

后续阶段继续从当前安装卡库重新计算未覆盖清单，以完整系列为单位推进；不能沿用本阶段的固定数量替代全库目标。每轮只把有足够 OCG 依据、全部分段完成的 `reviewed/manual` 条目计入覆盖。阶段结果和剩余量持续登记于[全库进度账本](card-annotation-progress.md)。

## 可直接交给下一个智能体的任务

> 按 `docs/card-annotation-agent-guide.md` 为我指定的卡号批次补全静态标注。先读取实际卡库与现有样本，再联网对照 KONAMI OCG 卡文和补充说明；保存冻结卡文、来源、逐效果结构与差异说明。未确认的内容保持草稿，不从关键词、标签缺失或脚本函数名推断完整规则。保留已有 ID、个人资料与备份，运行只读校验器及相关测试，审核后按项目规则提交和推送。交付本批完成卡号、来源、验证结果与尚待核对的问题。

## 2026-09-26 全库资料接收后的第一阶段

接收全库原始资料后，新增730张通常／通常调整怪兽、84张无效果额外／仪式怪兽以及急袭猛禽46张、超重武者47张，累计1502条；原595条逐项保留。来源文件完整性与规则含义分开核对，候选编号错配、地区和FAQ分页缺口见[接收审计](card-source-intake-2026-09-26.md)。逐卡清单、测试入口及阶段检查见[1.49.2验收](verification-1.49.2.md)。

## 2026-09-26 短卡文魔法陷阱第一阶段

四组100张通常魔法／通常陷阱完成逐卡处理，接纳395张，5张具体裁定依据不足而暂缓；本地累计1897条。新词表准确区分跳过阶段、改移对象、设置基本分、伤害转移、掷币／骰、公开后直接丢弃原应抽的卡等处理。旧1502条仅将急袭猛禽升阶魔法的“2只以上对象”迁移为明确开放上界，未改写其规则。

重跑本阶段：`python scripts/check_annotation_source_batch.py --runtime .local/YGOPro-Lite --manifest docs/card-annotation-batch-2026-09-26-short.json --source-pack .local/annotation-handoff/20260925-catalog-all-14981`。没有本地资料包时可省略最后一项，但不能声称来源快照已重验。公开清单包含接纳卡号、身份指纹、实际正反查询、规则边界和待核实原因，原始文本与采集脚本留在本地。

数据审核须区分卡片实例与卡名：“不包括正在发动的此卡”不能写成 `selector.exclude_codes=[本卡号]`，否则错误排除了同名其他盖卡。动作与来源／去向组合已绑定同一处理项；例如黄金柜的加手来源只能是除外状态，不能借用前一步的卡组来源。静态查询仍不判定当前局面可发动与否，完整检查见[1.49.3验收](verification-1.49.3.md)。

固定获赋效果以 `grant_effect.granted_effect` 记录自己的类别、标签、完整结构和费用／次数；父段 `own_tags` 明确自身标签，段落 `tags` 保留自身与子效果的展示并集。兼容 `then` 必须与子处理树一致。查询在同一个自身／固定获赋单元内匹配并显示依据，不把不同层的条件拼接；动态复制不推导未知对象能力。旧无此元数据条目保持原行为，个人TAG覆盖与卡文版本边界保留。新增受控值见[体系规范](card-annotation-system.md)。

## 2026-09-26 接续短卡文第二阶段

暂停断点的四组400张完成整合审核，接纳397张（通常魔法199、通常陷阱99、效果怪兽99），累计2294条；灵魂消灭、增压与连爆魔人仍待核实。34张新怪兽漏掉的通用TAG已补齐，68条TAG查询回归保留于[清单](card-annotation-batch-2026-09-26-short2.json)。旧1897条仅修正3张对象数量范围，不重写其他资料。

动态数量使用`count_rule`说明发动时计算依据，不能与固定数量或常量范围混用；查询和界面不执行表达式或求解实际局面。自身限制及仅召唤成功响应窗口封锁虽可检索，但不视为持续终场干扰。新动作定义、参数与反例见[体系规范](card-annotation-system.md)，重验来源时运行：

```powershell
python scripts/check_annotation_source_batch.py --runtime .local/YGOPro-Lite --manifest docs/card-annotation-batch-2026-09-26-short2.json --source-pack .local/annotation-handoff/20260925-catalog-all-14981 --supplemental-root .local/annotation-integration-20260926/phase3-supplemental
```

没有本地采集包时省略两个来源目录参数，只能验证结构和查询，不能声称来源快照已重新核验。完整范围和本次结果见[1.49.4验收](verification-1.49.4.md)；下一批继续读取当前Catalog与本地检查点，不把未完成候选计入正式覆盖。

## 2026-09-26 短卡文效果怪兽第二组

100张完成逐卡处理，接纳99张，累计2393条；再生僵尸因官方来源条件冲突保持待核实。保留破坏之剑士的两个独立本地编号，异画只在同名、类型、全文及身份属性一致后共用cid。攻击手续、伤害性质变更及事件决定的受伤者须按[体系规范](card-annotation-system.md)明确记录，不能借用回手处理、固定烧血或固定对方玩家来替代。具体来源与规则正反例见[清单](card-annotation-batch-2026-09-26-monsters2.json)，完整门禁见[1.49.5验收](verification-1.49.5.md)。

```powershell
python scripts/check_annotation_source_batch.py --runtime .local/YGOPro-Lite --manifest docs/card-annotation-batch-2026-09-26-monsters2.json --source-pack .local/annotation-handoff/20260925-catalog-all-14981
```

## 2026-09-26 通常陷阱第四组

从保留的20张检查点继续，固定100张全部处理，接纳95张，累计2488条；盗墓者、黏着的落穴、小子防御保留具体裁定缺口，王家的财宝、伤害瘦身因同一无编号段的两个独立效果尚不能隔离检索而暂缓。它们是本批明确未接纳项，不计入正式覆盖，也不伪造获赋关系来套用现有模型。

四项新动作、对方除外状态、回手费用及动态LP规则的定义见[体系规范](card-annotation-system.md)。义贼的极意书固定后续处理独立匹配，仍是原陷阱效果；作用于玩家的送墓保留解场候选，只有己方攻击宣言响应窗口的封锁不推导持续终场干扰。完整名单与验证见[本批清单](card-annotation-batch-2026-09-26-traps4.json)、[1.49.6验收](verification-1.49.6.md)。

```powershell
python scripts/check_annotation_source_batch.py --runtime .local/YGOPro-Lite --manifest docs/card-annotation-batch-2026-09-26-traps4.json --source-pack .local/annotation-handoff/20260925-catalog-all-14981
```
