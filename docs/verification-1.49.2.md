# 1.49.2 全库资料接收与第一阶段整合验收

日期：2026-09-26。本阶段新增 907 条正式静态标注，累计 1,502／14,716 张非衍生物；全库目标继续进行，不声明其余 13,214 张已完成。

## 变更范围

原有 595 条数据保持不变。新增通常／通常调整 730 张、无效果额外／仪式 84 张、急袭猛禽 46 张、超重武者 47 张。原始资料审计与来源问题见[接收报告](card-source-intake-2026-09-26.md)；逐卡身份、分段、指纹与测试向量见三个交付清单。

固定获赋效果在同一分段中保留独立类别、标签、结构与查询依据；不同匹配单元不拼接条件，动态复制不推断未知能力。标注详情、通用能力摘要、用途库条件、起手知识条件、终场比较与冻结路线展示均保留获赋效果自己的费用、时点、次数及另行满足边界。旧无元数据的授予效果和个人 TAG 覆盖保持兼容，不改写旧快照。伤害防止与造成效果伤害、守备攻击的计算数值、灵摆区放置、攻击转移和特定方法特召次数分别表达。

## 已执行的检查

| 检查 | 当前结果 |
| --- | --- |
| `check_card_annotations.py --runtime .local/YGOPro-Lite` | PASS 1,502 条：词表、来源引用、冻结卡文、实际卡库与全部分段 |
| `check_annotation_no_effect_batch.py` 加两份本地证据 | PASS 814 条：官方无效果分类、素材与效果分离、原始快照哈希、描述不产生能力 |
| `check_annotation_series_batch_20260926.py` 加全库来源包 | PASS 93 条、213 个机制正反查询、两个完整系列、926 个来源文件 |
| Python 标注单元测试 | PASS 42 项，含固定获赋单元、父子／子子条件不串接、旧格式、个人 TAG、动态复制边界 |
| 标注视图 Node 测试 | PASS 18 项，含获赋效果的费用／时点／次数及避免重复显示后续 |
| 完整 `npm test` | PASS 621 项 Python、252 项 Node，使用最终修复后的源码 |
| 能力／自动用途库回归 | PASS 18 项能力测试、12 项用途库测试；真实卡固定获赋约束进入条件摘要，持续魔法类型进入已有终场候选规则 |
| 真实数据消费链 | PASS 当前 Catalog → CardCapabilities → AnnotationKnowledge 条件 → 终场比较与冻结路线 HTML，动态复制、旧快照不回填及 HTML 转义边界保留 |
| `npm run test:desktop -- --annotations-only` | PASS 开发版，900／1280／1600 宽度、125% 缩放、资料浏览／查询及个人修正，`errors=[]`、`globalInput=false` |
| `npm run build:dir` | PASS 构建当前 1.49.2；28,888 个运行资源文件，原始采集包不随应用打包 |
| `npm run test:packaged -- --annotations-only` | PASS 新构建的 1.49.2，EXE 名称、描述、7 帧图标及同一后台标注验收，`errors=[]`、`globalInput=false` |
| 源码／打包资源一致性 | PASS 标注数据、词表、核心、能力／用途库及三个相关渲染文件共 8 个文件逐字节一致 |
| 独立审核 | 两轮发现并修复跨模块事实与条件摘要遗漏，第三轮真实消费链复核通过，无剩余阻断项；不据此声称全库规则核对完毕 |

来源快照只在本机保留。缺少原始包的环境可运行其他只读结构／查询检查，但不得宣称重新验证了本地来源文件。测试只使用隔离数据与后台 Electron 内部接口，不发送系统全局输入。

本地日志与检查证据位于 `.local/annotation-integration-20260926/`，后台桌面证据位于 `.local/evidence/electron-development-annotations-annotations-1492-final-48599b4ccea54261acb28589b804577f/` 和 `.local/evidence/electron-packaged-annotations-annotations-1492-packaged-c4f74b43d2a5413ab5d79b3d0345e25d/`。审核报告在 `.local/reviews/`。这批证据、原始 HTML、来源 ZIP、辅助索引及安装产物保留本地，未上传。
