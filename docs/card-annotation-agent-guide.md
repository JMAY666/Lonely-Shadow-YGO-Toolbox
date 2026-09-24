# 卡片标注交接指南

适用版本：1.47.0。供后续智能体在现有 46 张效果参考样本上逐批扩充。先读项目 `AGENTS.md` 与[体系规范](card-annotation-system.md)。本轮只维护静态卡片知识，不启动已封存的 AI 学习计划。系列中文名、徽记与封面是独立展示资料，按[系列标识制作流程](card-series-production-guide.md)补充，不把系列样例核对计入完整效果标注数量。

## 文件与交付范围

| 文件 | 用途 |
| --- | --- |
| `src/trainer/card-annotations.json` | 卡号、冻结卡文、效果结构、关系与来源 |
| `src/trainer/annotation-tags.json` | 通用标签、定义、受控词表 |
| `src/trainer/card_annotations.py` | 分段、校验、查询、个人覆盖层 |
| `scripts/check_card_annotations.py` | 只读检查来源、指纹、类型、分段覆盖 |

修改内置资料时保留旧条目与稳定 ID，不写用户运行目录、不覆盖个人标签、备注、牌组或备份。界面的「个人修正」只支持标签、备注与审核标记，不能代替完整结构标注。

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

当前查询保证条件在同一效果内逐项成立；未求解同一分支或同一处理项是否能同时满足全部条件。查到旋钮手②同时含回卡组与检索，并不意味着二选一能同时执行。静态标签也不能给出当前局面可发动结论。

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

## 可直接交给下一个智能体的任务

> 按 `docs/card-annotation-agent-guide.md` 为我指定的卡号批次补全静态标注。先读取实际卡库与现有样本，再联网对照 KONAMI OCG 卡文和补充说明；保存冻结卡文、来源、逐效果结构与差异说明。未确认的内容保持草稿，不从关键词、标签缺失或脚本函数名推断完整规则。保留已有 ID、个人资料与备份，运行只读校验器及相关测试，审核后按项目规则提交和推送。交付本批完成卡号、来源、验证结果与尚待核对的问题。
