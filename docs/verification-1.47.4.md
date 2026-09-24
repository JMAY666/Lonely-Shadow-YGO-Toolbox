# 1.47.4 验证记录 · 完整系列效果标注 100 张

日期：2026-09-25。以 `.local/YGOPro-Lite` 当前卡库为基准，先记录[119 张候选及最终处理结果](card-annotation-batch-2026-09-25.csv)，逐卡读取本地 `name/type/desc`，对照 KONAMI 官方 OCG 卡片页与 FAQ 补足情報。原始页面快照及研究映射只在 `.local/anno-batch4-research/` 保存，不打包发布。卡片身份是本地整数卡号；官方 cid、系列 setcode 和异画卡号分别记录。官方站内用户牌组评论未作为规则依据。

## 覆盖与来源

| 项目 | 数量／结果 |
| --- | --- |
| 基线内置标注 | 108 张 |
| 新增已核对、完整分段、`manual` 条目 | 100 张 |
| 原有同系列条目复核后保留 | 19 张；旧条目逐字未改 |
| 原有条目修正／新增条目待核对 | 0／0 |
| 新内置覆盖 | 208／14,716 张非衍生物；未标注 14,508 张 |
| 杀手旋律／杀手级调整曲 | 新增 8；当前 14／14 |
| 相剑 | 新增 14；当前 17／17 |
| 驱魔姐妹 | 新增 18；当前 19／19 |
| 转生炎兽 | 新增 39；当前 48／48 |
| 天威 | 新增 17；当前 17／17 |
| 原优先清单四张辅助卡 | 新增 4 |

每张新增条目均有官方卡片页与 FAQ URL、OCG 地区、核对日期、卡文冻结文本及指纹、全部分段及引用。本机保存 98 个不同 cid 的卡片页和 FAQ 页，另存一条个别裁定；旧 19 张另存 19 组当期快照。新增三张异画本地卡号单独入库，其中 42741438 与 42741437 同用官方 cid 16740，59242458 与 59242457 同用 cid 17157，41463182 与 41463181 同用 cid 13927；本地身份不合并。天威之鬼神、天威之拳僧无怪兽效果，仅标素材规则并明确 `no_effect`。

圣母颂歌③另依据[KONAMI 个别 Q&A 23548](https://www.db.yugioh-card.com/yugiohdb/faq_search.action?fid=23548&ope=5&request_locale=ja&tag=-1)核对：原本持有者为对方的超量素材不能返回对方额外卡组；没有自己原本持有的超量怪兽素材时不能发动。原页面保存在 `.local/anno-batch4-research/faq-detail-23548.html`。本轮新卡无未解决的逐卡裁定；静态 TAG 仍只代表卡文能力，不证明当前局面可发动或互斥分支可同时处理。

## 分批与完整检查

累计新增 20／40／60／80／100 张时分别运行带实际 runtime 的标注校验、来源／指纹／分段核对与关键查询正反例。检查覆盖除外费用和处理、发动无效与效果无效、处理时丢弃和费用丢弃、超量素材取除是费用还是处理、互斥分支、场上子区域、额外素材及自身/对方执行的区别。每次还与 Git 基线比较，确认原 108 条未变化。另对官方补足情報明确给出分类的 96 个怪兽效果做逐段交叉检查，未发现类别不一致。

| 命令 | 本次结果 |
| --- | --- |
| `python scripts/check_card_annotations.py --runtime .local/YGOPro-Lite` | PASS 208，词表、来源、指纹、卡文与全段覆盖 |
| `python scripts/check_annotation_series.py --runtime .local/YGOPro-Lite` | PASS 20 系列／35 代表样例 |
| `python scripts/check_annotation_batch4.py --runtime .local/YGOPro-Lite --expected 100 --require-snapshots` | PASS 100，官方本地快照、区域与效果查询正反例；五系列全员 `reviewed/full` |
| `python -m unittest discover -s tests -p test_card_annotations.py -q` | 25 项通过，含新增分支／素材结构拒绝测试 |
| `npm test` | 574 项 Python、246 项 Node 通过 |
| `npm run test:desktop -- --annotations-only` | PASS；`annotations-result.json` 中 `errors=[]`、`globalInput=false`，系列目录、查询及个人修正检查通过 |
| `npm run build:dir` | PASS；1.47.4 当前源码构建，离线资源清单 28,888 项；标注服务、资料、词表及本轮清单与工作区 SHA-256 一致 |
| `npm run test:packaged -- --annotations-only` | PASS；EXE 品牌与七种图标帧检查通过；标注验收 `errors=[]`、`globalInput=false` |

桌面与首次打包验收分别使用唯一 `YGO_TEST_RUN=annotations-1474-20260925-bb217c3e`、`annotations-1474-packaged-20260925-719efb24`，通过后台 Electron 和隔离测试数据执行；无系统鼠标移动或全局按键。正式测试、构建和打包日志保留在 `.local/anno-batch4-*.log`，截图与 JSON 验收记录在 `.local/evidence/electron-{development,packaged}-annotations-…/`。个人 TAG、备注、牌组、方案和备份均未写入；上一版本的个人卡文指纹隔离保持有效。已封存的 AI 学习计划未启动。

README、标注体系、交接指南与候选清单随资料更新；新受控取值的定义、正反例及旧取值兼容边界见[体系规范 §4](card-annotation-system.md)。静态查询尚不求解同一互斥分支的条件共存，也不代替当前局面规则引擎验证。
