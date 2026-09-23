# 1.42.1 验证记录

日期：2026-09-23。范围：[第一点实施方案](going-second-opening-implementation.md)，使用说明见[后攻起手分析](going-second-opening.md)。

## 检查

| 检查 | 结果 |
| --- | --- |
| `npm test` | Python 463 项、JavaScript 221 项通过 |
| `npm run test:desktop -- --intelligence-only --opening-only` | 后攻录入、条件提示、补充资源、卡牌详情、窄窗口、迟到响应、用途维护、保存失败保留、自动页面、换局、重启恢复通过 |
| `npm run test:packaged -- --intelligence-only --opening-only` | EXE 品牌资源与相同专项通过 |
| `npm run test:desktop -- --duel-only` | 原先攻教程、分支、卡牌详情、导航、窄窗与快捷键生命周期回归通过 |
| `npm run test:desktop -- --automatic-only` | 原逐步卡组捕获、先后攻、起手冻结、返回及断线门禁回归通过 |
| `npm run test:desktop -- --automatic-only --smart-only` | 四个平台的智能识别页面合同模拟、取消、迟到响应、下一局、先攻工作区与后攻入口通过 |
| `npm run build` | Windows x64 解包版与 ZIP 生成于新目录 `release/1.42.1/` |
| 包内资源比对 | 133 个应用资源文件与当前源码 SHA-256 一致 |

使用后台 Electron、独立数据目录和渲染器截图，没有移动系统鼠标或发送全局按键。正式测试报告内前端错误列表为空。测试中的按键与指针只作用于本应用测试窗口／内部接口。

## 合同覆盖

- A01：双主边界、三系列接近、父子归组、共享副本、用途排除与源 TAG 不变。
- A02：复制路线去重、区域顺序保留、发动／处理／素材分开、少样本只给候选；正式录制事件重建与效果覆盖分别检查。
- A03：实际起手与任意手牌费用、隐性第二手牌费用、卡组组件上手、同名剩余副本及分支前提。
- A04—A05：G／锁鸟、吸引者、结界波条件提示；护航资料、多用途实体计数、无手坑、无方案与未知用途。
- A06—A07：服务端只读字段拒绝、修订与来源版本冲突、人工覆盖不被候选替换、卡文变化后保留旧覆盖、缺损文件拒绝覆盖、写入失败保持旧版本。
- A08：自动服务只使用服务端冻结起手，不相信客户端提交的替代手牌；旧局、读取中断、改起手、离开及晚到响应被拒绝或清除。
- A09—A10：960px 后攻页与情报站无横向溢出，详情与失败提示可用，开发／打包版重启恢复；先攻和既有情报站分类切换回归。

## 证据与数据

正式截图和结构化报告仅保存在 `.local/evidence/`：

- `electron-development-intelligence-opening-1421-dev-final/`
- `electron-packaged-intelligence-opening-1421-pack/`
- `electron-development-duel-opening-1421-regression/`
- `electron-development-automatic-opening-1421-regression/`
- `electron-development-automatic-opening-1421-smart/`
- `opening-1421-package-source.json`

继续沿用 `.local/`、`release/`、缓存等忽略规则。个人设置和备份仅写入隔离测试运行目录；应用不会改写原卡库、TAG、正式方案或对局记录。已有 `release/1.41.0/` 和 `release/1.42.0/` 保留。自动审批拒绝了按清单删除本轮测试运行资源的清理操作，故保留缓存，没有进行该批删除。

## 限制

没有重新连接真人客户端完成四平台实战后攻联调；自动入口的新增验证为服务端合同与后台页面模拟。源事件、资源与 UI 测试采用隔离合成记录，不把它们作为真实牌组的合法展开证据。没有执行第 2—5 点的对手识别、交坑时点、通用解场搜索或自动操作，也没有恢复 AI 学习计划。终场共享次数、完整有效性和实际斩杀仍按资料不足显示待核对，不宣称逐局引擎验证。

首次测试发现旧后攻占位文案断言及智能识别测试夹具缺字段，已更新夹具与断言后通过；截图检查中发现深色主题提示背景问题，已修正并在最终包重新检查。全部检查通过后再审核、提交和推送。
