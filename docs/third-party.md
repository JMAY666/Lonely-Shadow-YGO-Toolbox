# 第三方来源

- 客户端：[Fluorohydride/ygopro](https://github.com/Fluorohydride/ygopro/tree/30f173a678bdade61a7b37f736dec1771e9afef9)，固定提交 `30f173a678bdade61a7b37f736dec1771e9afef9`。
- 核心：[Fluorohydride/ygopro-core](https://github.com/Fluorohydride/ygopro-core/tree/8ff3583846ea40d82f60fbdb438cd464c77169c1)，固定提交 `8ff3583846ea40d82f60fbdb438cd464c77169c1`。
- 客户端上游许可证副本：[GNU GPL version 2](../licenses/YGOPro-GPL-2.0.txt)。`src/lite`、`single_thread.inc` 与 `patches/ygopro-lite.patch` 是该客户端的本地修改／适配，不代替上游完整源码。
- Lua、Irrlicht、SQLite、libevent、FreeType、libjpeg-turbo、libpng、zlib、XZ/liblzma 与 Premake 的版本、下载地址和 SHA-256 见 [source-lock.json](../scripts/source-lock.json)，各自许可证保留在解包后的上游目录。
- 卡牌数据库、图片和效果脚本复用用户已有的独立工作副本，不随仓库发布。工具不修改卡牌定义、不下载更新卡牌资源。

补丁脚本从 `.local/pristine` 保存的原始文件生成统一 diff，并将手写适配文件复制至 `.local/upstream/gframe`；重复运行不会重复叠加补丁。
