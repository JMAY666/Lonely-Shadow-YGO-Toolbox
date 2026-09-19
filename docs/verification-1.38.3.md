# 1.38.3 手坑效果标记与备注

手坑资料增加效果选择和逐效果的并列备注，复用终场标记的效果编辑组件与校验。原用途说明、使用条件和文件夹保留；手坑与终场备注各自保存。删除文件夹或通过 TAG 管理保留成员时，不丢失效果资料。

效果以卡面文本快照保存。卡库更新后，旧效果及备注可转入待核对区域，再手动归入当前效果。旧资料读取时补充默认字段，不立即改写文件；实际保存前沿用原子写入、版本冲突检查和备份。

## 检查结果

- `npm test`：407 项 Python 测试、208 项 JavaScript 测试通过。新增检查覆盖手坑效果与多条备注持久化、终场资料独立、TAG／文件夹编辑保留效果、空备注效果、取消标记、旧数据只读兼容及写入前备份、无效效果拒绝、缺卡与卡面文本变化时保留旧备注和待核对内容。
- `node --check`：`src/trainer/web/intelligence.js`、`desktop/intelligence-smoke.cjs` 和 `desktop/intelligence-layout-smoke.cjs` 通过。
- `npm run test:desktop -- --intelligence-only`：通过效果勾选、取消勾选、多条备注增删改、取消编辑、保存失败与切换模块后的输入保留、重复选卡、独立终场备注、文件夹删除、TAG 同步及完整应用／服务重启后的数据核对。原有终场标注、断点与组合应对流程也通过。
- `npm run test:desktop -- --intelligence-only --layout-only`：通过分类切换、筛选、资料高亮、固定保存栏及窄窗口布局检查。核对 1440×950、900×650、760×844、390×844 的渲染器截图，手坑效果文本及并列备注没有横向溢出，卡图正常加载。
- `npm run test:packaged -- --intelligence-only`：打包程序通过同一功能与重启流程，产品名与图标检查通过，运行只使用包内运行环境。
- 桌面验收均使用隐藏 Electron 窗口及隔离资料，没有渲染器错误；没有移动系统鼠标或发送全局按键。

截图与结果保留在 `.local/evidence/electron-development-intelligence-handtrap-1383-layout/`、`.local/evidence/electron-development-intelligence-handtrap-1383-functional/` 和 `.local/evidence/electron-packaged-intelligence-handtrap-1383-functional/`。

## 构建

`npm run build` 成功生成 `release/1.38.3/win-unpacked/` 与 Windows x64 ZIP。包内 116 个服务／网页资源文件、7 个桌面源码文件与源码 SHA-256 一致，应用版本为 1.38.3。ZIP 共 289 个文件项，未发现个人运行目录、备份或 Python 缓存路径。

## 数据与范围

沿用 `.local/`、`release/` 的忽略规则，隔离验收资料和生成包仅保留本地。没有新增依赖，没有删除个人资料、备份或旧版本。未改变规则引擎、正常训练随机数、方案或断点记录格式。

未重新验收全部原生决斗和外部客户端识别。示例备注仅为隔离验收内容，不代表战略收益或规则合法性验证。
