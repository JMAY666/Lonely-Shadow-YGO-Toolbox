# 1.49.9 卡片标注复审与修正

日期：2026-09-27。用户要求检查GPT-6 Luna刚处理的卡片。本次复审其已写入工作区的stage03全部88张，以及未合并stage04的16张候选；未继续补卡，未执行stage04第二个20项作者脚本。

## 结论和范围

原88张的机械检查通过，但仍存在实际规则错误和缺失信息。此次修正46个本地卡号，公开清单记录49项规则或信息修正，包括费用、对象及效果类别等实质错误，也包括必发说明等缺失信息。另补齐己方限制的`self_only`，用实际用途查询避免把自锁当成对手干扰。原2,682条逐项保持不变，88条经过复审后保留，正式累计2,770／14,716，尚余11,946条。原100项中的12张结构缺口仍待核实；不把它们计入覆盖。

原386项完整清单前340项合计282核准、58待核实。第四阶段16张只在本地候选中，未导入程序；复审发现7个候选卡号的实质问题后撤销该阶段已审核状态，原稿保留。最新第四阶段决策为0核准、42未完成复核、4结构缺口，合并仍被流程阻止。不能把旧“16张核准”或旧机械验证结果当作当前有效状态。

## 关键发现

- 巨眼费用实际为1个素材，原稿写成2个；背反料理人②完全漏掉素材费用。
- 龙王霍普雷②只有效果无效，原稿混入狮子霍普雷的攻击力减半；其①也能响应自己的取对象效果。
- 隐形水母怪②不取对象；霍普雷·胜光的获赋●也不取对象。
- 水泡侠①是无连锁效果，原稿误判为非效果手续并漏掉特召能力；剧毒人作为永续陷阱时②是陷阱效果，且仅双方主要阶段。
- 黑飙①使自己和对方都承受相同战伤，原稿误写成把自己的伤害转给对方；其获赋●是诱发即时效果。
- 恶刃死魔的攻击力提升没有回合结束时限，原稿增加了时限；玩家攻击限制不能依赖成功破坏。
- 暂时除外后的返回独立登记，不作为特殊召唤。魔界弦乐手抽卡只要求破坏成功，天堂弦乐手伤害按破坏数量，不能额外要求送墓。
- 作者自己的4条语义断言重复了错误结论，已依官方证据修正：水泡侠①、剧毒人②、彗星之指套拳王获赋条件、霍普雷·胜光获赋条件。因此“断言通过”不能作为独立规则证据。

## 逐卡修正

本地异画卡号独立保留。同一FAQ可支持多个严格peer卡号；不会把它们合并成同一个本地身份。来源用于静态规则核对，不表示引擎已完整验证所有个别裁定。

| 本地卡号与卡名 | 修正内容 | 规则来源 |
| --- | --- | --- |
| 62517849 No.39 希望皇 霍普·翻倍 | m1：叠放召唤排除本卡；攻击力加倍与禁止直接攻击分别记录。 | [KONAMI补足](https://www.db.yugioh-card.com/yugiohdb/faq_search.action?cid=14220&ope=4&request_locale=ja) |
| 62542673 命运英雄 恶魔主宰人 | m1：补齐暂时除外后的原表示回场处理，不产生连锁、不算特殊召唤。；m2：暗属性HERO自锁从未被无效的效果处理后适用，不是从发动瞬间适用。 | [KONAMI补足](https://www.db.yugioh-card.com/yugiohdb/faq_search.action?cid=23344&ope=4&request_locale=ja) |
| 63060238 元素英雄 烈焰侠 | m2：属性及攻守变化至回合结束；融合自锁要求发动和效果未被无效，从处理后适用。 | [KONAMI补足](https://www.db.yugioh-card.com/yugiohdb/faq_search.action?cid=11419&ope=4&request_locale=ja) |
| 63362460 命运英雄 神性人 | m1：破坏成功才造成500伤害，二者视为同时；对象也可位于场地或灵摆区域。 | [KONAMI补足](https://www.db.yugioh-card.com/yugiohdb/faq_search.action?cid=12707&ope=4&request_locale=ja) |
| 63956833 银河天翔 | m1：补齐实际效果无效与整回合召唤自锁的独立处理和TAG，不能只把无效藏在攻守变化说明中。 | [KONAMI补足](https://www.db.yugioh-card.com/yugiohdb/faq_search.action?cid=13943&ope=4&request_locale=ja) |
| 64184058 命运英雄 决意人 | m1：结束阶段检索是原诱发效果的延迟处理，不在结束阶段另起连锁。 | [KONAMI补足](https://www.db.yugioh-card.com/yugiohdb/faq_search.action?cid=12704&ope=4&request_locale=ja) |
| 65305468 未来No.0 未来皇 霍普 | m2：FAQ明确本卡战破后也可从墓地或表侧除外状态发动夺取控制权，不能只登记怪兽区。 | [KONAMI补足](https://www.db.yugioh-card.com/yugiohdb/faq_search.action?cid=11413&ope=4&request_locale=ja) |
| 65305469 未来No.0 未来皇 霍普 | m2：FAQ明确本卡战破后也可从墓地或表侧除外状态发动夺取控制权，不能只登记怪兽区。 | [KONAMI补足](https://www.db.yugioh-card.com/yugiohdb/faq_search.action?cid=11413&ope=4&request_locale=ja) |
| 66262416 命运英雄 梦乡人 | m1：保护正在战斗的己方D-HERO；并规范离场除外的延迟说明。 | [KONAMI补足](https://www.db.yugioh-card.com/yugiohdb/faq_search.action?cid=13153&ope=4&request_locale=ja) |
| 66547759 No.23 冥界的灵骑士 兰斯洛特 | m3：③是必发的诱发即时效果，不能作为可自由保留的对手干扰。 | [KONAMI补足](https://www.db.yugioh-card.com/yugiohdb/faq_search.action?cid=11459&ope=4&request_locale=ja) |
| 67173574 混沌No.102 光堕天使 贵魔 | m2：条件满足时必须发动，不能表述为任意发动。 | [KONAMI补足](https://www.db.yugioh-card.com/yugiohdb/faq_search.action?cid=11073&ope=4&request_locale=ja) |
| 67557908 No.4 猛毒刺胞 隐形水母怪 | m2：②不取对象，在处理时选择水属性怪兽；①仅改变怪兽属性，③特召数量下限为1。 | [KONAMI补足](https://www.db.yugioh-card.com/yugiohdb/faq_search.action?cid=16424&ope=4&request_locale=ja) |
| 68679595 兽装合体 狮子霍普雷 | m2：减半基于当前攻击力，不是原本攻击力。 | [KONAMI补足](https://www.db.yugioh-card.com/yugiohdb/faq_search.action?cid=16421&ope=4&request_locale=ja) |
| 69170557 混沌No.40 机关傀儡-魔界弦乐手 | m1：抽卡只要求破坏成功，送墓只用于后续伤害数值；①必须发动。 | [KONAMI补足](https://www.db.yugioh-card.com/yugiohdb/faq_search.action?cid=11015&ope=4&request_locale=ja) |
| 69610924 No.17 海恶龙 | m1：无素材时禁止直接攻击，不能登记成允许直接攻击的动作。 | [KONAMI补足](https://www.db.yugioh-card.com/yugiohdb/faq_search.action?cid=9656&ope=4&request_locale=ja) |
| 71921856 No.79 燃烧拳击手 新星之帝环拳士 | m3：删除不存在的同名最多1只限制；对象至少1只，并保留「时」的错过时点边界。 | [KONAMI补足](https://www.db.yugioh-card.com/yugiohdb/faq_search.action?cid=11118&ope=4&request_locale=ja) |
| 75253697 No.72 行列怪兽 战车之飞车 | m1：补齐战斗伤害变更的通用TAG，动作查询与TAG查询应一致。 | [KONAMI补足](https://www.db.yugioh-card.com/yugiohdb/faq_search.action?cid=10843&ope=4&request_locale=ja) |
| 75402014 龙装合体 龙王霍普雷 | m2：②只有效果无效，没有攻击力减半；①被自己效果取对象时也可响应。 | [KONAMI补足](https://www.db.yugioh-card.com/yugiohdb/faq_search.action?cid=16000&ope=4&request_locale=ja) |
| 75433814 No.40 机关傀儡-天堂弦乐手 | m2：伤害按破坏数量计算，不能增加送墓条件。 | [KONAMI补足](https://www.db.yugioh-card.com/yugiohdb/faq_search.action?cid=10216&ope=4&request_locale=ja) |
| 77205367 混沌No.96 黑飙 | m1：①使双方承受相同战斗伤害，不是把自己的伤害转给对方；●是诱发即时效果。；m1：补齐战斗伤害变更的通用TAG，动作查询与TAG查询应一致。 | [KONAMI补足](https://www.db.yugioh-card.com/yugiohdb/faq_search.action?cid=10777&ope=4&request_locale=ja) |
| 79625003 闪光No.37 蜘蛛鲨 | m1：补齐暂时除外后的原表示回场处理，不产生连锁、不算特殊召唤。 | [KONAMI补足](https://www.db.yugioh-card.com/yugiohdb/faq_search.action?cid=21065&ope=4&request_locale=ja) |
| 79747096 混沌No.1 混沌源数门-空 | m1：条件满足时必须发动，不能表述为任意发动。 | [KONAMI补足](https://www.db.yugioh-card.com/yugiohdb/faq_search.action?cid=15379&ope=4&request_locale=ja) |
| 79979666 元素英雄 水泡侠 | m1：官方明确①是无连锁效果，不是非效果手续；补回特殊召唤能力及TAG。 | [KONAMI补足](https://www.db.yugioh-card.com/yugiohdb/faq_search.action?cid=6393&ope=4&request_locale=ja) |
| 80117527 No.11 巨眼 | m1：费用为1个超量素材；本回合已宣言攻击后不能发动。 | [KONAMI补足](https://www.db.yugioh-card.com/yugiohdb/faq_search.action?cid=9861&ope=4&request_locale=ja) |
| 80764541 No.44 白天马 | m1：当前官方卡文与冻结卡文均要求表侧表示，不能只凭旧FAQ简写放宽对象。 | [KONAMI补足](https://www.db.yugioh-card.com/yugiohdb/faq_search.action?cid=10702&ope=4&request_locale=ja) |
| 80796456 No.70 大罪蛛 | m1：补齐暂时除外后的原表示回场处理，不产生连锁、不算特殊召唤。 | [KONAMI补足](https://www.db.yugioh-card.com/yugiohdb/faq_search.action?cid=12891&ope=4&request_locale=ja) |
| 81003500 元素英雄 死灵萨满 | m1：条件满足时必须发动，不能表述为任意发动。 | [KONAMI补足](https://www.db.yugioh-card.com/yugiohdb/faq_search.action?cid=6644&ope=4&request_locale=ja) |
| 81330115 No.30 破灭之酸液石人 | m3：条件满足时必须发动，不能表述为任意发动。 | [KONAMI补足](https://www.db.yugioh-card.com/yugiohdb/faq_search.action?cid=9858&ope=4&request_locale=ja) |
| 81866673 命运英雄 冲刺人 | m3：确认抽到的怪兽发生在发动时，不是处理中的手卡公开能力或额外费用；不能据此生成看手TAG。 | [KONAMI补足](https://www.db.yugioh-card.com/yugiohdb/faq_search.action?cid=6753&ope=4&request_locale=ja) |
| 82697249 No.59 背反之料理人 | m2：补回遗漏的取除1个超量素材费用。 | [KONAMI补足](https://www.db.yugioh-card.com/yugiohdb/faq_search.action?cid=12548&ope=4&request_locale=ja) |
| 82697428 幻影英雄 突袭魔女 | m1：实际破坏范围为对方魔法陷阱卡，补齐魔陷、场地和灵摆区域的查询范围。 | [KONAMI补足](https://www.db.yugioh-card.com/yugiohdb/faq_search.action?cid=9074&ope=4&request_locale=ja) |
| 83414006 幻影英雄 剧毒人 | m2：当作永续陷阱时②是陷阱效果，不是怪兽诱发即时效果；仅双方主要阶段。 | [KONAMI补足](https://www.db.yugioh-card.com/yugiohdb/faq_search.action?cid=9071&ope=4&request_locale=ja) |
| 83512285 超银河 | m1：对象在处理时变里侧或攻击力低于2000仍解放；成功解放和特召视为同时。 | [KONAMI补足](https://www.db.yugioh-card.com/yugiohdb/faq_search.action?cid=14981&ope=4&request_locale=ja) |
| 84013237 No.39 希望皇 霍普 | m2：条件满足时必须发动，不能表述为任意发动。 | [KONAMI补足](https://www.db.yugioh-card.com/yugiohdb/faq_search.action?cid=9575&ope=4&request_locale=ja) |
| 84013238 No.39 希望皇 霍普 | m2：条件满足时必须发动，不能表述为任意发动。 | [KONAMI补足](https://www.db.yugioh-card.com/yugiohdb/faq_search.action?cid=9575&ope=4&request_locale=ja) |
| 84013239 No.39 希望皇 霍普 | m2：条件满足时必须发动，不能表述为任意发动。 | [KONAMI补足](https://www.db.yugioh-card.com/yugiohdb/faq_search.action?cid=9575&ope=4&request_locale=ja) |
| 84013240 No.39 希望皇 霍普 | m2：条件满足时必须发动，不能表述为任意发动。 | [KONAMI补足](https://www.db.yugioh-card.com/yugiohdb/faq_search.action?cid=9575&ope=4&request_locale=ja) |
| 85121942 混沌No.105 燃烧拳击手 彗星之指套拳王 | m2：持有指定超量素材而取得●的条件不是永续效果；●的独立效果类别保持。 | [KONAMI补足](https://www.db.yugioh-card.com/yugiohdb/faq_search.action?cid=10533&ope=4&request_locale=ja) |
| 85507811 元素英雄 光辉新宇侠 | m2：条件满足时必须发动，不能表述为任意发动。 | [KONAMI补足](https://www.db.yugioh-card.com/yugiohdb/faq_search.action?cid=6988&ope=4&request_locale=ja) |
| 85747929 银河光子龙 | m3：调整等级的对象必须具有等级，不能选择超量或连接怪兽。 | [KONAMI补足](https://www.db.yugioh-card.com/yugiohdb/faq_search.action?cid=18189&ope=4&request_locale=ja) |
| 86165817 邪心英雄 恶刃死魔 | m2：攻击力提升无回合结束时限；攻击自锁在未被无效的处理后独立适用，不依赖成功破坏。 | [KONAMI补足](https://www.db.yugioh-card.com/yugiohdb/faq_search.action?cid=14586&ope=4&request_locale=ja) |
| 86282581 邪心英雄 暗黑骑魔 | m3：补齐表侧除外状态的发动区域，并记录原持有者与最初去向限制。 | [KONAMI补足](https://www.db.yugioh-card.com/yugiohdb/faq_search.action?cid=20770&ope=4&request_locale=ja) |
| 86532744 闪光No.39 希望皇 霍普一 | m1：破坏并除外的去向按被除外卡的持有者保留双方除外区域，不默认全进自己除外状态。 | [KONAMI补足](https://www.db.yugioh-card.com/yugiohdb/faq_search.action?cid=10977&ope=4&request_locale=ja) |
| 87758525 至爱英雄 闪光火焰翼侠 | m2：条件满足时必须发动，不能表述为任意发动。 | [KONAMI补足](https://www.db.yugioh-card.com/yugiohdb/faq_search.action?cid=22693&ope=4&request_locale=ja) |
| 87758526 至爱英雄 闪光火焰翼侠 | m2：条件满足时必须发动，不能表述为任意发动。 | [KONAMI补足](https://www.db.yugioh-card.com/yugiohdb/faq_search.action?cid=22693&ope=4&request_locale=ja) |
| 87911394 混沌No.39 希望皇 霍普雷·胜光 | m2：持有指定超量素材而取得●的条件不是永续效果；●的独立效果类别保持。；m2：获赋的●不取对象，不能误写成针对被攻击怪兽的目标效果。 | [KONAMI补足](https://www.db.yugioh-card.com/yugiohdb/faq_search.action?cid=10651&ope=4&request_locale=ja) |

## 未合并候选及草稿

第四阶段7个已发现问题的候选卡号：

| 卡号 | 问题 |
| --- | --- |
| 89516305 雪月花美神 | 植物族对象需表侧；三个分支的伤害步骤许可不同，需要分别表达。 |
| 90162951 极饿捕鸟蛛 | 同时特召多只怪兽只造成600伤害；按特召事件次数，不按怪兽数量。 |
| 90307498 新宇智者 | 离场诱发区域是墓地或表侧除外状态，原稿错误包含手卡和额外卡组。 |
| 91691605 钻头人 | 贯通应登记专用动作，原稿只有一般伤害变更，漏掉贯通动作检索。 |
| 91714772／91714773 银河防卫机器人 | 只能选择怪兽，原稿放宽为所有“卡”；漏掉本回合光属性特殊召唤自锁。 |
| 92362073 银河卫龙 | 战伤减半作用于对方玩家，原稿错误绑定对方怪兽区域。 |

第二个20项作者脚本未执行、未验证，本次不将其升格为核准资料。静态查看已发现93431862《D-HERO 扣杀人》起动区域被写成手卡，以及93347961《元素英雄 火焰翼侠-火焰一击》的无视召唤条件处理又被附加“必须融合召唤”的无依据限制；需恢复工作时逐卡重审，不直接运行旧脚本。

## 来源和实际检查

- 逐项对照88张冻结卡文、真实分段、所引日本KONAMI卡页、补足与必要FAQ；再次获取165个不同官方卡页／FAQ索引页面，均保存成功，FAQ中的卡文与原缓存没有变化。网页正文及原始HTML保留本地，不能用获取成功代替逐卡语义审核。
- 全库词表、来源、冻结卡文、安装卡库卡文及分段覆盖：2,770条通过；系列资源20系列／35样例通过。
- 当前正式资料的完整批次检查：88张、195条实际查询、220条语义断言、5条用途边界，614个来源文件SHA-256通过。使用`check_annotation_source_batch.py --full`检查当前正式资料；原不可变集成候选仅作为历史证据保留。
- 新增13项独立规则回归：原Luna数据12项断言失败、1项因缺失返回字段报错；修正版13项全部通过。
- 完整`npm test`：700项Python、257项Node通过。修改的桌面验收脚本另通过Node语法检查。
- 最终后台开发版`npm run test:desktop -- --annotations-only`与新构建1.49.9的`npm run test:packaged -- --annotations-only`均通过。实际API、界面详情和能力事实验证1个素材费用、不取对象、无连锁特召、陷阱类别、通用TAG正反例及未合并草稿隔离；未移动系统鼠标、未发送全局按键。
- 两种最终验收均为隔离数据、后台窗口，`errors=[]/globalInput=false`。新包160个运行资源SHA-256与当前`src/trainer`逐项一致，`app.asar`版本、名称与入口匹配；EXE名称、描述及7帧图标通过。未借用旧版本验收结果。

最终包为`.local/annotation-audit-20260927/package-1499-final/`，截图及验收报告分别位于`.local/evidence/electron-development-annotations-stage03-audit-final-development-1499/`与`.local/evidence/electron-packaged-annotations-stage03-audit-final-packaged-1499/`。

## 数据保留与发布

沿用`.gitignore`对`.local`、依赖、构建、凭据和个人资料的排除规则，未删除用户数据、来源或备份。原始工作区文件、两个阶段的决策和旧候选、未执行作者脚本、165份当前页面、完整检查日志和本次包均只保留本地。复审备份位于`.local/annotation-audit-20260927/before/`。提交前尝试清理本次被最终包替代的中间构建目录`package-1499/`，自动审批审核以`blocked by policy`拒绝执行；该目录保留本地并排除上传。最终包、正式证据、日志、原始资料和备份保留，不为清理版本管理范围删除用户资料。

README、交接指南、批次流程、覆盖账本和体系规范按本次实际结果同步；未恢复封存AI学习计划。本地提交及现有`origin/main`推送依项目审核规则执行，最终提交哈希和远端结果以Git核验为准。
