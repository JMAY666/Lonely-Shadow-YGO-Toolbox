# 1.48.0 统一卡片能力引用验收

日期：2026-09-25。范围：共享只读能力服务、卡片详情、三类用途标记、能力筛选、起手与实战参考、历史快照和终场能力说明。

## 数据保护

不改写内置 498 张标注，不迁移个人标记，不删除用户资料。新保存的方案冻结标注投影，旧方案不补造历史。分享导出排除全局个人能力备注。`.local/` 与 `release/` 延用现有忽略规则，资源、测试档案、截图与构建包仅保留本地。

## 检查记录

| 命令／检查 | 实际结果 |
| --- | --- |
| `npm test` | PASS：592 项 Python、249 项 Node；新增 16 项 Python、3 项 Node 能力引用检查。 |
| `python scripts/check_card_annotations.py --runtime .local/YGOPro-Lite` | PASS：498 张；词表、来源、冻结卡文、当前指纹和分段覆盖。内置标注文件未改动。 |
| `npm run test:desktop -- --capabilities-only` | PASS：全部 498 张投影、构筑筛选、用途采纳、个人备注保留、跨模块修改同步、TAG 搜索、历史隔离、起手参考及真实重启。 |
| `npm run test:desktop -- --intelligence-only` | PASS：终场实例应用、并列备注、取消与失败保存、手坑成员／目录／TAG、断点步骤及重启；900／1440 像素布局。 |
| `npm run test:desktop -- --annotations-only` | PASS：系列卡牌夹、别名、封面、效果查询、详情和个人修正原有流程。 |
| `npm run build:dir` | PASS：1.48.0 Windows 解压运行版。 |
| `npm run test:packaged -- --capabilities-only` | PASS：1.48.0 实际 EXE；品牌及 7 个图标帧、跨模块专项与重启，在移除开发工具 PATH 后运行。 |
| 打包源码一致性 | PASS：141 个 Python／JS／CSS／HTML／JSON 文件与工作区内容逐一相同。 |
| 静态检查与视觉核对 | 修改的 JS 语法检查、Git 空白检查通过；查看本应用渲染器的卡组编辑与情报站截图，主题、折叠区及文字布局正确。 |

所有桌面结果 `errors=[]`、`globalInput=false`。截图来自隐藏的应用渲染器，没有移动系统鼠标或发送全局按键。测试与运行日志保留在 `.local/reviews/capability-integration-20260925/`；专项证据在 `.local/evidence/electron-development-capabilities-capabilities-v1480/` 和对应 `electron-packaged-...` 目录，原有页面的回归证据分别在 `electron-development-intelligence-capabilities-v1480/` 与 `electron-development-annotations-capabilities-v1480/`。

首轮检查发现并修复了非异步初始化中的 `await`、轻量 CLI 入口的可选依赖兼容，以及 CRLF／LF 导致的旧效果片段对应失败。上述问题修复后重新执行相关检查。开发运行资源原先缺失，从已有 1.47.7 包的清单恢复公共资源并逐文件校验；原生源码归档按现有锁文件 SHA256 恢复。本地卡库 SHA256 与原标注基线一致，没有替换用户数据。

静态能力的共享、历史冻结和终场说明已验证；本次没有新增原生展开算法，也没有重跑全部原生路线场景。

## 实现边界

能力筛选和用途候选引用已核对分段，不判定当前可发动性。起手角色统计、路线计分和实战合法性仍沿用原有模块；新增能力构成提供核对依据，不宣称获得新的已验证展开或可用阻抗次数。外部客户端完整局面读取范围保持原样。
