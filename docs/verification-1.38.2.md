# 1.38.2 情报站工作区

情报站按现有卡组编辑、展开管理的布局重新整理。顶部保留分类与主操作，左栏集中搜索、筛选和资料列表，右栏显示卡牌身份、用途备注、效果或断点步骤。取消多层大容器边框和重复说明，统一标题、表单标签、间距与选中状态。

进入分类时打开首条资料，列表名称可直接选择编辑，卡图保留原有预览入口。卡名／卡号和 TAG 常驻，其他卡牌条件收进可展开的筛选区并显示已选数量。筛选不清空当前编辑；未保存切换仍需确认。桌面编辑内容独立滚动，保存操作保留在底部。选卡与来源汇总临时占用完整工作区，来源读取失败也保留返回入口。

## 检查结果

- `npm test`：403 项 Python 测试、208 项 JavaScript 测试通过。
- `node --check src/trainer/web/intelligence.js` 与 `node --check desktop/intelligence-layout-smoke.cjs`：通过。
- `npm run test:desktop -- --intelligence-only --layout-only`：通过分类数量、自动选择、选中高亮、组合筛选及条件数量、取消放弃修改、保存栏位置、断点步骤排序、选卡与汇总的工作区切换、收起导航及响应式布局检查。
- `npm run test:desktop -- --intelligence-only`：通过通用／局部标注复用、保存失败保留输入、版本冲突核对、手坑与 TAG 同步、文件夹管理、断点与组合应对、删除和完整应用／服务重启后的数据核对。
- `npm run test:desktop -- --intelligence-only --merge-only`：通过单卡／全部合并、并列备注增删改、来源追踪、展开复用、旧文本效果归入以及重启持久化回归。
- `npm run test:packaged -- --intelligence-only --layout-only`：通过同一布局流程，另验证来源请求失败后可返回编辑；程序产品名、图标检查通过，打包进程只使用内置运行环境。
- 桌面验收均运行于隐藏 Electron 窗口和隔离资料目录，最终结果没有渲染器错误；没有移动系统鼠标或发送全局按键。

检查了 1440×950、900×650、760×844、390×844 的渲染器截图。终场、手坑、断点、空状态、选卡、来源汇总及导航收起均已覆盖；卡图加载正常，未发现横向溢出或左右栏重叠。小于桌面最小窗口的尺寸只在验收实例中临时解除限制，正式程序窗口限制保持原值。标题栏既有的 900／1280／1600 宽度与 125% 缩放检查也通过。

截图和检查结果保留在 `.local/evidence/electron-development-intelligence-layout-1382-final/` 与 `.local/evidence/electron-packaged-intelligence-layout-1382-final/`。功能回归与合并回归分别保留在 `.local/evidence/electron-development-intelligence-layout-1382-regression-final/` 和 `.local/evidence/electron-development-intelligence-layout-1382-merge/`。

## 构建与范围

`npm run build` 成功生成 `release/1.38.2/win-unpacked/` 和 Windows x64 ZIP。116 个服务／网页资源文件及 7 个桌面源码文件与源码 SHA-256 一致；打包后的应用元数据与源码配置一致，构建专用字段按打包工具的正常行为移除。ZIP 共 289 个文件项，未发现个人运行目录、备份或 Python 缓存路径。

本次没有修改规则引擎、正常训练随机数、资料保存格式或既有个人文件；没有重新验收全部原生决斗和外部客户端识别。界面里的示例资料来自隔离验收数据，不代表策略有效性验证。

沿用并检查 `.local/`、`release/` 等已有忽略规则，没有新增依赖或修改排除范围。旧版本、个人资料、备份与验收产物全部保留本地，不进入源码提交。
