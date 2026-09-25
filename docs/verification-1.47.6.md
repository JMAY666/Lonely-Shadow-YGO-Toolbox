# 1.47.6 验证记录 · 六个完整系列新增 100 张

日期：2026-09-25。依据当前 `.local/YGOPro-Lite` 的 `Catalog` 与 `CardSeries` 重新选择六个完整系列，并在修改前保存[101 个本地卡号的候选及最终清单](card-annotation-batch-2026-09-25-phase3.csv)。卡牌身份仍是本地整数卡号，官方 `cid` 只用于来源，系列 `setcode` 只用于成员集。保留本地译名、完整 `name/type/desc`；官方站内用户牌组评论不作为裁定。

## 覆盖及来源

| 项目 | 实际结果 |
| --- | --- |
| 原覆盖／本阶段新增／新覆盖 | 302／100／402 张 |
| 当前非衍生物可标注／尚未标注 | 14,716／14,314 张 |
| 原有复核后跳过／修正／新卡待核对 | 1／0／0 张 |
| 影灵衣 | 新增 24，已有 1；系列 25／25 |
| 召唤兽 | 新增 15；系列 15／15 |
| 珠泪哀歌族 | 新增 15；系列 15／15 |
| 神碑 | 新增 15；系列 15／15 |
| 白森林 | 新增 18；系列 18／18 |
| 星杯 | 新增 13；系列 13／13 |

本轮 100 张使用 96 个不同官方 `cid`。四个未直接出现在辅助映射中的本地异画编号，在同名、同类型、同完整卡文指纹校验后才映射至对应官方卡页，仍作为不同本地卡号逐条保存。每张新增条目有 `frozen_text`、`digest()` 指纹、`segments(desc,type)` 全段、效果结构、OCG 规则地区、核对日期与备注来源引用；原有 302 张的 JSON 条目逐项保持不变。三张星杯通常怪兽的官方 FAQ 没有额外补足条目，依据官方卡片页完整描述标 `no_effect`，保留故事文案。官方卡页、FAQ 和原有《影灵衣的万华镜》当期复核原始 HTML 保存在 `.local/anno-batch6-research/`，不进入 Git 或安装包。

逐卡裁定没有未解决项；静态效果结构及 TAG 不能推断特定局面可发动或互斥分支可同时满足。全库其余 14,314 张继续分阶段处理，不视为无效果。

## 逐批检查与机制边界

累计 20／40／60／80／100 张时，均运行实际 runtime 标注校验、系列资料校验、来源快照／指纹／全部分段及机制查询正反例检查；旧 302 条复核后未覆盖。关键边界包括影灵衣效果解放与费用解放、召唤兽发动无效与效果无效、珠泪哀歌族融合素材和处理时送墓、神碑互斥分支与额外怪兽区域、白森林魔陷送墓费用与同调素材、星杯的非效果召唤手续及墓地／场上来源。官方 FAQ 给出明确分类的 145 个怪兽编号效果与本批结构类别逐项交叉比对，未发现类别不一致。新受控动作和区域具备定义、正反例、兼容规则及校验；专项单元测试覆盖同调素材后续召唤、调整化时限、场上回手来源和额外怪兽区域查询方向。

## 最终验收

| 命令 | 结果 |
| --- | --- |
| `python scripts/check_card_annotations.py --runtime .local/YGOPro-Lite` | PASS 402；词表、来源、冻结卡文、实际指纹和全部分段 |
| `python scripts/check_annotation_series.py --runtime .local/YGOPro-Lite` | PASS 20 个展示系列／35 个代表样例；六个本批系列另由专项检查确认全员 `reviewed/full` |
| `python scripts/check_annotation_batch6.py --runtime .local/YGOPro-Lite --expected 100 --require-snapshots` | PASS 100；100 个卡号的 OCG 卡页／FAQ 快照、逐效果来源引用和机制查询正反例 |
| `npm test` | PASS；575 项 Python、246 项 Node 测试通过 |
| `npm run test:desktop -- --annotations-only` | PASS；`annotations-result.json` 的 `errors=[]`、`globalInput=false` |
| `npm run build:dir` | PASS；1.47.6 当前源码构建，离线资源清单 28,888 项 |
| `npm run test:packaged -- --annotations-only` | PASS；EXE 品牌及七种图标帧，标注验收 `errors=[]`、`globalInput=false` |

桌面与打包测试分别使用唯一 `YGO_TEST_RUN=annotations-1476-20260925-243e552f`、`annotations-1476-packaged-20260925-a566d4f6`，通过后台 Electron 和隔离测试数据执行，不移动系统鼠标或发送全局按键。测试、构建、打包日志位于 `.local/anno-batch6-*.log`；正式截图和 JSON 证据留在 `.local/evidence/`。最终文档写入后重建并再次做打包验收，以确保包内说明与当前源码数据一致。个人 TAG、备注、牌组、方案、备份及个人标注不写入；AI 学习计划保持封存。来源快照、正式验收证据与包留在本地。
