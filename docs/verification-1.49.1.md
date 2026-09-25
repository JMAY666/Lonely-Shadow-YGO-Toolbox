# 1.49.1 验证记录 · 六个完整系列新增 97 张

日期：2026-09-25。承接现有 1.49.0 跨模块能力实现和 498 张内置标注，从当前 `.local/YGOPro-Lite` 的 `Catalog` 与 `CardSeries` 重新选取六个完整系列，在数据修改前保存[97 个不同本地整数卡号的候选与交付清单](card-annotation-batch-2026-09-25-phase5.csv)。逐号核对完整本地 `name/type/desc`、KONAMI 官方 OCG 卡片页与 FAQ 补足情報；官方站内用户牌组评论未作规则依据。官方 `cid`、系列 `setcode` 与异画本地编号分开处理，不改卡库译名。

## 覆盖和来源

| 项目 | 实际结果 |
| --- | --- |
| 原覆盖／新增／新覆盖 | 498／97／595 张 |
| 当前非衍生物可标注／尚未标注 | 14,716／14,121 张 |
| 旧条目修正／已有复核跳过／新卡待核对 | 0／0／0 张 |
| 卫星闪灵 | 新增 12；系列 12／12 |
| 铁兽 | 新增 21；系列 21／21 |
| 龙辉巧 | 新增 20；系列 20／20 |
| 随风旅鸟 | 新增 11；系列 11／11 |
| 十二兽 | 新增 15；系列 15／15 |
| 朋克 | 新增 18；系列 18／18 |

97 个本地编号对应 95 个不同官方 `cid`；两张本地异画编号先经同名、同类型、同完整卡文指纹核对后才映射至其基础卡官方页，仍各自保存条目。所有新增条目均有 `frozen_text`、现有 `digest()` 指纹、`segments(desc,type)` 全段、逐效果结构、OCG 规则地区、核对日期与备注来源引用。原有 498 条逐项不变。95 个官方卡页及 FAQ 原始 HTML 保留在 `.local/anno-batch8-research/`，不纳入 Git 或安装包。

本阶段无逐卡未决裁定。静态结构和 TAG 命中仍不能判定特定对局可发动、次数能否支配整条连锁或互斥分支可否同时成立。

## 分批与机制检查

累计新增 20／40／60／80／97 张时运行实际 runtime 标注校验、系列资料校验、官方快照／指纹／全分段核查及关键机制查询正反例，并核对旧 498 条未改写。重点区分：非入连锁特殊召唤与效果特召；发动无效、效果无效及召唤无效；仪式素材、解放费用及其替代；效果送墓与费用送墓；自身失去LP、支付LP与效果伤害；回合内回溯自锁和不回溯自锁；超量素材附着、取除费用和取除来源替代；立即通常召唤与提高通常召唤次数。官方 FAQ 明确分类的 138 个本批编号怪兽效果与结构类别交叉核对，未见不一致。新受控动作及次数取值的定义、正反例、兼容与校验见[标注体系](card-annotation-system.md)。

## 最终验收

| 检查 | 实际结果 |
| --- | --- |
| `python scripts/check_card_annotations.py --runtime .local/YGOPro-Lite` | PASS 595；词表、来源、冻结卡文、当前指纹及全部分段 |
| `python scripts/check_annotation_series.py --runtime .local/YGOPro-Lite` | PASS 20 个展示系列／35 个代表样例；六个本批系列另由专项检查确认全员 `reviewed/full` |
| `python scripts/check_annotation_batch8.py --runtime .local/YGOPro-Lite --expected 97 --require-snapshots` | PASS 97；实际卡库、官方卡页和 FAQ 快照、逐效果来源引用及机制查询正反例 |
| `npm test` | PASS；604 项 Python、249 项 Node 测试通过 |
| `npm run test:desktop -- --annotations-only` | PASS；`annotations-result.json` 中 `errors=[]`、`globalInput=false` |
| `npm run build:dir` | PASS；当前 1.49.1 源码与数据生成 Windows 解压版，离线资源清单 28,888 项 |
| `npm run test:packaged -- --annotations-only` | PASS；EXE 品牌及七种图标帧、标注验收 `errors=[]`、`globalInput=false` |

桌面与首次打包验收分别使用唯一 `YGO_TEST_RUN=annotations-1491-20260925-405648fd`、`annotations-1491-packaged-20260925-2cc70552`，通过后台 Electron 和隔离数据执行，不移动系统鼠标或发送全局按键。文档写入后使用当前源码再构建独立验收包并复验，逐文件比对包内标注资料、词表、README、规范、交接指南、进度账本、清单和本记录的 SHA-256。日志在 `.local/anno-batch8-*.log`；正式截图和 JSON 证据保留在 `.local/evidence/`。

本次不写用户真实运行目录，不重新执行 1.49.0 的个人用途资料迁移，不触碰个人 TAG、备注、牌组、方案或备份；AI 学习计划继续封存。来源快照、正式证据与必要备份保留本机。后续跨模块用途统计会随新标注扩大静态覆盖，但本批未将其当作当前局面规则验证，也未在真实个人数据上重复迁移。
