# 第三方来源

- 客户端：[Fluorohydride/ygopro](https://github.com/Fluorohydride/ygopro/tree/30f173a678bdade61a7b37f736dec1771e9afef9)，固定提交 `30f173a678bdade61a7b37f736dec1771e9afef9`。
- 核心：[Fluorohydride/ygopro-core](https://github.com/Fluorohydride/ygopro-core/tree/8ff3583846ea40d82f60fbdb438cd464c77169c1)，固定提交 `8ff3583846ea40d82f60fbdb438cd464c77169c1`。
- 客户端上游许可证副本：[GNU GPL version 2](../licenses/YGOPro-GPL-2.0.txt)。`src/lite`、`single_thread.inc` 与 `patches/ygopro-lite.patch` 是该客户端的本地修改／适配，不代替上游完整源码。
- Lua、Irrlicht、SQLite、libevent、FreeType、libjpeg-turbo、libpng、zlib、XZ/liblzma 与 Premake 的版本、下载地址和 SHA-256 见 [source-lock.json](../scripts/source-lock.json)，各自许可证保留在解包后的上游目录。
- 基础卡牌数据库、图片和效果脚本复用用户已有的独立工作副本，不随 Git 仓库发布。本机 Windows 应用包包含运行必需资源，属于本地交付；未上传或公开分发。用户可在全局设置中从 [MyCard 官方超先行页面](https://mycard.world/ygopro/arena/#/superpre) 对应的 HTTPS CDN 下载 `.ypk`；下载资源与恢复备份仅存本地，不纳入 Git 或内置基础资源包。工具保留原包，由现有 YGOPro 引擎加载官方卡牌定义和 Lua 脚本，不替换引擎程序。详见[超先行补丁](superpre.md)。
- Electron 44.3.0（MIT）及 Chromium 通知随应用根目录的 `LICENSE.electron.txt` / `LICENSES.chromium.html` 保留；开发依赖版本固定在 `package-lock.json`。[Electron 进程模型](https://www.electronjs.org/docs/latest/tutorial/process-model)说明主进程与独立渲染窗口的关系。
- Python 3.14.5 Windows x64 嵌入式发行版来自 [Python 官方发行页面](https://www.python.org/downloads/release/python-3145/)，归档 URL 与 SHA-256 固定在 `scripts/desktop-lock.json`；许可证保留在 `resources/python/LICENSE.txt`。[嵌入式发行版说明](https://docs.python.org/3.14/using/windows.html#the-embeddable-package)。
- 桌面包的 `resources/notices/native-sources.zip` 包含上述固定原生源码归档、各归档内的许可证、补丁和构建脚本；不包含原始安装的私人数据。运行所需 VC 运行库静态链接在当前 YGOPro x64 构建中，Python 的运行库随其官方嵌入包携带。

补丁脚本从 `.local/pristine` 保存的原始文件生成统一 diff，并将手写适配文件复制至 `.local/upstream/gframe`；重复运行不会重复叠加补丁。
