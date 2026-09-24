# 1.47.3 验证记录 · 卡片标注纠错与个人修正版本隔离

日期：2026-09-24 至 2026-09-25。范围：修复个人覆盖层跨卡文版本串用，次元吸引者费用说明、三战之才等 7 张 TAG、35 项快速效果标志、访问码语者②处理区域；强化资料一致性与区域查询检查。没有新增卡牌，覆盖仍为 108 张。

个人文件兼容旧版读取，第一次保存前备份，未知／旧指纹的覆盖层保留为历史，不参与新效果查询和确认；保存失败时不改变内存与原文件。新增迁移、重启、备份、保存失败、查询正反例、错误资料拒绝与历史内容转义检查。验收仅使用隔离目录和后台桌面接口。

实际结果：

| 检查 | 结果 |
| --- | --- |
| `npm test` | 573 项 Python、246 项 Node 测试通过 |
| `python scripts/check_card_annotations.py --runtime .local/YGOPro-Lite` | 108 条通过，核对词表、来源、卡文指纹、完整分段和新增一致性规则 |
| `python scripts/check_annotation_series.py --runtime .local/YGOPro-Lite` | 20 系列 / 35 代表样例通过 |
| 卡片相关 Python / 界面单测 | 65 项 / 17 项通过，已包含在完整测试中 |
| `npm run test:desktop -- --annotations-only` | 通过，`errors=[]`、`globalInput=false` |
| `npm run build:dir` | 1.47.3 构建成功，离线资源清单含 28,888 项 |
| `npm run test:packaged -- --annotations-only` | 通过；EXE 品牌与七种图标帧检查通过，`errors=[]`、`globalInput=false` |
| 打包内容比对 | 标注服务、卡片资料、词表和界面脚本与工作区逐字节一致 |

新增回归实际覆盖旧卡文确认、卡文变化、内置资料更新、重启、重新核对保存；旧个人 TAG 不污染新效果查询，原备注和移除标签记录保留，旧版文件首次保存有完整备份。模拟写盘失败后内存和已保存文件不变。资料回归验证三战之才的正反查询、访问码语者的场上子区域及墓地反例，以及快速效果和 TAG 错误重新出现时校验失败。桌面与打包验收还检查了这些真实卡号的 API 结果和新版个人文件指纹。

费用说明依据 [KONAMI OCG FAQ 14540](https://www.db.yugioh-card.com/yugiohdb/faq_search.action?fid=14540&ope=5&request_locale=ja&tag=-1)，原始页面与摘要指纹保存在 `.local/annotation-fix-1.47.3-sources/`。其他效果的来源引用及全部冻结卡文保留。新增检查只验证明确的一致性约束，不等同于逐条完成 108 张卡的全部裁定审查或引擎实战验证。

完整测试、开发版、构建和打包日志分别在 `.local/annotation-fix-1.47.3-{tests,desktop,build,packaged}.log`。桌面证据位于 `.local/evidence/electron-{development,packaged}-annotations-fix-1473/`；验收使用 `YGO_TEST_RUN=fix-1473` 隔离目录，没有接管系统鼠标或全局键盘，没有启动封存的 AI 学习计划。

README、标注规范、交接指南和下一批补卡提示词已同步，补卡提示词与本验证记录也随本地发行目录提供。忽略规则无需变更；安装产物、个人数据、来源快照和验收证据只保留在本地。提交前仅清理已确认无进程使用、对应源码存在且没有符号链接的 `tests/__pycache__` 与 `scripts/__pycache__` 中 54 个可重建缓存文件，合计 1,164,945 字节；其他运行资源、旧版本、正式证据及备份保留。
