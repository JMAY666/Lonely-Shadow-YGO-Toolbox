# 1.42.2 后攻分析阅读与资料复核

日期：2026-09-23。范围：复核已实现的第一点，调整默认信息层级，补充当前杀手级调整曲构筑的关键资料。第 2—5 点与 AI 学习计划保持原状态。

## 复核发现与处理

| 发现 | 本次处理 |
| --- | --- |
| 实战页同时展开全部效果原文、统计、重复少样本提示和整副构筑通用资料。 | 起手结论、配合、路线前提优先；资料与依据默认折叠，完整内容仍可查看。 |
| 选满起手后主卡组候选仍占大量空间。 | 分析完成后收起选牌区；起手预览、槽位选择及修改入口保留。 |
| 提示员、自然蔷薇鞭没有用途说明，用户难以理解这手牌。 | 新增卡文核对与条件化分工，说明召唤入口及蔷薇鞭上手后的可用方式。 |
| “同调／融合”宽泛检索标签被直接列成小轴并参与主系列共享折算。 | 仅在本分析中单列为通用支援标签，不修改原 TAG 库或个人分类。 |
| 实际录制路线因随机结果未确认被统一标为“待核对”。 | 保留原随机条件检查，明确显示“含随机结果”；不把有启动入口写成完整路线已验证。 |
| 场地魔法的卡片发动被混入不明编号效果。 | 复用既有卡片发动识别，单列动作，不计作主要效果证据；保留旧备注关联标识。 |
| 缺少卡库资料时，无法可靠判断额外怪兽类型。 | 列入待核对项，不按非调整推断，也不阻断其他已知资源的分析。 |

## 补充资料

14 张卡包括提示员、混音手、唱片师、旋钮手、削波手、音轨制作人、场地、本家同调速攻魔法、再混音手、红印鉴唱片师、响度战争、B2B、自然蔷薇鞭和同调超车。数据见 `src/trainer/opening-kewl-tune.json`，逐条包含官方链接与本地卡文快照；对外显示用途摘要，完整依据按需展开。

主要机制依据：[提示员](https://www.db.yugioh-card.com/yugiohdb/card_search.action?cid=21956&ope=2&request_locale=ja)、[混音手](https://www.db.yugioh-card.com/yugiohdb/card_search.action?cid=21953&ope=2&request_locale=ja)、[唱片师](https://www.db.yugioh-card.com/yugiohdb/card_search.action?cid=21955&ope=2&request_locale=ja)、[旋钮手](https://www.db.yugioh-card.com/yugiohdb/card_search.action?cid=22531&ope=2&request_locale=ja)、[音轨制作人](https://www.db.yugioh-card.com/yugiohdb/card_search.action?cid=21957&ope=2&request_locale=ja)、[场地](https://www.db.yugioh-card.com/yugiohdb/card_search.action?cid=21962&ope=2&request_locale=ja)、[B2B](https://www.db.yugioh-card.com/yugiohdb/card_search.action?cid=22551&ope=2&request_locale=ja)、[自然蔷薇鞭 Q&A](https://www.db.yugioh-card.com/yugiohdb/faq_search.action?cid=8102&ope=4&request_locale=ja)、[同调超车](https://www.db.yugioh-card.com/yugiohdb/card_search.action?cid=16256&ope=2&request_locale=ja)。

蔷薇鞭限制的是魔法／陷阱卡的发动，不是全部魔陷效果；官方 Q&A 同时说明它是场上适用的永续效果。提示员可从手牌取得另一只调整，因此“该组件上手就完全无用”不成立。该配合说明是卡文下的条件推导，不是已重放的一卡动结论。

卡片可否投入随规则环境与时间变化；本次没有确定用户当前对局使用哪份禁限表。核对时官方 OCG 页面对自然蔷薇鞭显示禁止，本资料仍保留效果参考，不能据此断言在当前环境允许使用。没有自动调整或删除构筑。

## 检查记录

| 检查 | 状态 |
| --- | --- |
| `npm test` | Python 470 项、JavaScript 223 项通过 |
| `npm run test:desktop -- --intelligence-only --opening-only` | 通过：手动／自动冻结起手、受控编辑、迟到响应、失败保存恢复、真实重启及复制实例布局 |
| `npm run test:desktop -- --duel-only` | 通过：原有先攻／后攻入口、手牌预览、流程与尺寸回归；无应用错误 |
| `npm run build` | 通过：生成 1.42.2 解压目录与 Windows ZIP |
| `npm run test:packaged -- --intelligence-only --opening-only` | 最终打包版通过上述起手专项、复制实例、真实重启及程序名称／图标检查；无应用错误 |
| 窗口与截图 | 1440×960、960×800 下无横向溢出；详情默认收起且能够展开，已人工复核截图 |
| 包内资源 | 按现有构建过滤规则，136 个服务与前端文件的 SHA-256 均与源码一致，解压目录与 ZIP 两份均匹配；ZIP 无 Python 字节码缓存 |

第一次桌面检查发现新增脚本未加入服务端静态资源白名单，已修复。第二次复制实例检查通过，但该测试增加方案后仍用旧分析结果做重启断言，出现来源差异；测试现隔离复制样例并重新读取比较基线。这些失败保留在本地，不能当作最终通过证据。

测试使用后台 Electron、隔离目录及应用渲染器截图，没有发送全局输入。用户构筑与方案仅以只读副本用于复现，不提交到 Git；交付前已再次核对两份源文件的 SHA-256，均未变化。该构筑中的 14 张资料卡均与当前卡文、类型匹配。当前测试不代表真人后攻对局、斩杀或通用阻抗次数验证。

开发版证据位于本地 `electron-development-intelligence-opening-layout-dev3`，决斗回归位于 `electron-development-duel-opening-layout-duel-regression`，最终包证据位于 `electron-packaged-intelligence-opening-layout-pack-final2`；均在忽略的 `.local/evidence/` 下。新资料和布局代码进入版本管理，个人副本、验收截图及 1.42.2 发行包只保留本地。

提交前核对三个已退出的旧验收目录，仅清理与保留运行包清单大小、哈希一致的可重建资源：共 86,661 个文件、3,836,841,699 字节。个人测试设置、方案、日志、清单、正式验收证据和既有版本保留；清理清单在本地 `opening-layout-review/cleanup.json`。本次无需修改 `.gitignore`。

## 尚存边界

卡文资料不会补造录制样本。原路线只有一组、存在随机结果、持续效果证据不足或缺少逐局续接验证时，仍如实保留。后续扩大覆盖需要实际方案与规则证据，本次没有将它们改成确定结果。
