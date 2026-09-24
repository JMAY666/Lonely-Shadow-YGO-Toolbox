# 1.47.5 验证记录 · 四个完整系列新增 94 张

日期：2026-09-25。本阶段承接 1.47.4 的 208 张内置标注，按当前 `.local/YGOPro-Lite` 卡库重新选取烙印、死狱乡、自奏圣乐、青眼四个完整系列。先保存[100 个不同本地卡号的候选与交付清单](card-annotation-batch-2026-09-25-phase2.csv)，逐卡读取 `name/type/desc`，对照 KONAMI 官方 OCG 卡片页与 FAQ 补足情報；官方站内用户牌组评论未作规则依据。官方 cid、系列 setcode 与本地异画卡号分开处理，不改卡库译名。

## 覆盖与来源

| 项目 | 本次实际结果 |
| --- | --- |
| 基线／新增／新覆盖 | 208／94／302 张 |
| 当前非衍生物可标注／尚未标注 | 14,716／14,414 张 |
| 原有条目复核后跳过／修正／新卡待核对 | 6／0／0 张 |
| 烙印 | 新增 24；系列 25／25 |
| 死狱乡 | 新增 8 个此前未计入烙印的卡号；系列 11／11 |
| 自奏圣乐 | 新增 18；系列 19／19 |
| 青眼 | 新增 44；系列 46／46 |

烙印剧城同时属于烙印与死狱乡，只按整数卡号新增一次。青眼白龙、青眼究极龙等异画卡号逐号保存；17 个无法直接由辅助索引查到 cid 的本地卡号，先比对同名、同 `type`、同完整卡文指纹的基础卡，再核对官方 OCG 页。新增 21 张无怪兽效果卡，保存完整通常怪兽描述或融合素材规则并显式声明 `no_effect`，没有从描述关键词生成效果。每张新条目都有完整 `frozen_text`、现有 `digest()` 指纹、`segments(desc,type)` 全段覆盖、OCG 来源 URL／日期／引用。70 个不同 cid 的官方卡片页和 FAQ、原有 6 张的当期复核快照仅保留在 `.local/anno-batch5-research/`，不上传。

本批无未解决的逐卡裁定；静态效果 TAG 与结构化查询仍不证明当前局面可发动，也不求解互斥分支能否同时满足组合条件。后续目标为当前未标注的 14,414 张，按系列分阶段推进，重新计算候选而不把自动草稿计入已核对。

## 分批及完整检查

累计新增 20／40／60／80／94 张时分别运行带实际 runtime 的标注校验、官方来源与快照、指纹、分段覆盖和查询正反例；每次确认旧 208 条未改写。机制检查包括费用与效果送墓／除外、发动无效与效果无效、处理时丢弃与丢弃费用、回手与回额外卡组、超量素材取除替代、非效果召唤手续，以及青眼卡通龙的攻击支付与贯通战斗伤害。对官方补足情報明确分类的 95 个新怪兽效果逐段交叉比对，未发现类别不一致。

| 命令 | 本次结果 |
| --- | --- |
| `python scripts/check_card_annotations.py --runtime .local/YGOPro-Lite` | PASS 302；词表、来源、卡文指纹和全段覆盖 |
| `python scripts/check_annotation_series.py --runtime .local/YGOPro-Lite` | PASS 20 系列／35 代表样例 |
| `python scripts/check_annotation_batch5.py --runtime .local/YGOPro-Lite --expected 94 --require-snapshots` | PASS 94；本机官方快照、正反查询与四系列全员 `reviewed/full` |
| `npm test` | PASS；574 项 Python、246 项 Node 测试通过 |
| `npm run test:desktop -- --annotations-only` | PASS；`annotations-result.json` 中 `errors=[]`、`globalInput=false` |
| `npm run build:dir` | PASS；1.47.5 当前源码构建，离线资源清单 28,888 项，标注服务、卡片资料、词表、清单和进度账本与工作区 SHA-256 一致 |
| `npm run test:packaged -- --annotations-only` | PASS；EXE 品牌与七种图标帧检查通过；标注验收 `errors=[]`、`globalInput=false` |

桌面与首次打包验收分别使用唯一 `YGO_TEST_RUN=annotations-1475-20260925-6ab493de`、`annotations-1475-packaged-20260925-952f0c7e`，通过后台 Electron 和隔离测试数据执行，不移动系统鼠标或发送全局按键。测试、构建及打包日志保留在 `.local/anno-batch5-*.log`；正式截图和 JSON 证据保留在 `.local/evidence/`。个人 TAG、备注、牌组、方案、备份及旧个人标注绑定状态不写入；AI 学习计划继续封存。README、体系规范、交接指南与覆盖统计同步更新，来源快照、正式验收证据和包保留本地。版本提交、推送与 GitHub About 结果在完成全部检查后报告。
