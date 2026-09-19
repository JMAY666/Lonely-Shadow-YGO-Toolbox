# YGOPro 对局数据读取路径

记录日期：2026-09-17。1.22.0 接入开局状态和先后攻标记，1.23.0 接入初始发牌消息与我方手牌核对。1.27.0 新增独立的智能识别开局构筑接口：限定正式对局早期，并核对服务器初始化的我方区域数量与完整构筑、前后快照和进程身份；详见 [智能识别说明](smart-recognition.md)。完整局面跟踪仍为后续开发方向。原逐步卡组捕捉入口仍要求处于编辑器。

## 适用客户端

- 进程：`YGOPro.exe`，Windows x64，显示版本 1.036.2。
- 可执行文件 SHA-256：`55dd3e8ea4e9a0f24bb2b038e4c95f6e266140469be3480924ff1e57dda1e629`。
- 以下位置均来自该构建的本地实测，不能仅凭版本号套用于其他可执行文件。模块基址每次通过 Toolhelp 获取；绝对地址会受 ASLR 和进程重启影响。
- 使用 `OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ)` 与 `ReadProcessMemory`，不注入、不写内存、不发送游戏输入。连接身份使用进程路径、创建时间及镜像指纹共同核对。

## 已验证的位置

设 `B` 为 YGOPro 主模块基址，`G = read_u64(B + 0x693e20)` 为 `mainGame` 指针。

| 数据 | 地址或偏移 | 结构 / 校验 |
| --- | --- | --- |
| `DeckManager.current_deck` | `B + 0x6b4330` | 主／额外／副三个连续的 24 字节 vector |
| 编辑器状态 | `G + 0x114b` | `is_building`，下一个字节为 `is_siding`；正常编辑应为 `01 00` |
| 卡牌拖动状态 | `G + 0x1894` | `is_draging` 和 `is_starting_dragging` 两字节；读取时均应为 0 |
| `ClientField` | `G + 0x13a0` | 起始 8 字节是虚表指针；区域 vector 从 `G + 0x13a8` 开始 |
| 对局区域 vector | `G + 0x13a8 + 24 × (2 × zone + player)` | zone 顺序：牌库、手牌、怪兽区、魔陷区、墓地、除外、额外；每区两个玩家 |
| 构筑卡牌编号 | `CardDataC* + 0` | `uint32`；类型位在 `+0x28` |
| 对局卡牌编号 | `ClientCard* + 0x88` | `uint32 code`；不是构筑里的 CardDataC 结构，不能混用偏移 |
| 对局基础状态 | `G + 0xe08` | `isStarted`；随后 `+1 isInDuel`、`+2 isFinished`、`+3 isReplay`、`+5 isFirst`、`+6 isTag`、`+7 isSingleMode` |
| 回合和玩家类型 | `G + 0xe24` / `G + 0xf30` | 32 位回合号 / 8 位玩家类型；普通玩家类型小于 7 |
| 准备窗口 | `read_u64(G + 0x3158)` | `wHostPrepare` |
| 猜拳窗口 | `read_u64(G + 0x32d8)` | `wHand` |
| 先后攻选择窗口 | `read_u64(G + 0x32f8)` | `wFTSelect` |
| GUI 可见位 | 上述 GUI 对象 `+0xa8` | 8 位布尔，已结合对应虚表 getter/setter 和真实画面验证 |
| 我方手牌 vector | `G + 0x13d8` | 普通玩家视角的 `hand[0]`，24 字节 vector |
| 卡牌控制者／区域 | `ClientCard* + 0xd1` / `+0xd2` | 8 位控制者须为 0、区域须为 2（手牌） |
| 当前游戏消息缓存 | `B + 0x7d9970` | `last_successful_msg`；当前非重试消息处理前复制入此缓存 |
| 消息缓存长度 | `B + 0x7d9960` | 64 位长度；只解码第 0 回合我方的 `MSG_DRAW` |

先后攻监测实现见 `src/trainer/ygopro_order.py` 和 `src/trainer/web/duel-order.js`。`STOC_DUEL_START` 会先令 `isStarted=true` 并清零回合，此时尚未完成猜拳；不能直接使用该时点的 `isFirst`。正式 `MSG_START` 赋值 `isInDuel` 和 `isFirst`，再等待第 1 回合确认结果，避免连续读取恰好落在字段赋值中间。

初始发牌解码：消息字节 `90`，随后 1 字节服务器玩家序号、1 字节张数、每张 4 字节卡号。卡号清除 `0x80000000` 状态位。先攻时我方服务器玩家为 0、后攻时为 1；客户端已通过 `LocalPlayer` 将普通玩家视角的我方区域映射到 `hand[0]`。仅解码我方消息，不读取对方牌号；校验精确长度及重复读取一致性。先保存候选发牌消息，手牌区按份数完整匹配后冻结，避免发牌动画只出现一两张时提前确认。

实现见 `src/trainer/ygopro_opening.py`、`src/trainer/web/duel-opening.js`。实测两局先攻与一局后攻，均在第 0 回合保存完整 5 张；后攻第 2 回合当前手牌为 6 张，原起手快照仍为 5 张。采样中断无法证明局次连续时，不复用旧快照作为当前起手。

vector 为三个 64 位指针 `[begin, end, capacity_end]`，元素为 64 位卡牌对象指针。必须验证有序边界、8 字节对齐、最大数量、可读范围，再读 `(end-begin)/8` 个指针。怪兽区与魔陷区容器含空位，指针 0 表示没有卡牌，不能当作有效卡牌解引用。

本次实测 `player=0` 的手牌与画面下方我方六张手牌逐项相符；这只验证了该次正常玩家视角。观战、录像、换边和其他模式需独立核对玩家映射，不能直接假定下标 0 始终是用户本人。

## 本次证据与含义

- 在进行中的真实对局中，`current_deck` 得到 40／15／15 张，与进入对局前捕捉的构筑完全一致。它表示已加载的完整构筑，不是牌库剩余数量，也不表示洗牌后的顺序。
- 同一时点，我方区域数据为牌库 34 张、手牌 6 张、额外 15 张；六张手牌的 `ClientCard.code` 与画面逐项对应。牌号、名称和个人卡组完整列表仅保留在本地证据中。
- 本次没有验证牌库中未知牌的顺序、途中换边、断线重连、BO3 换副、随机效果后持续跟踪、双方卡牌控制权变化和完整局面重建。未知卡号 0 必须保留为未知，不能猜测。
- “决斗准备”页仅改变下拉选择时，不能信任 `current_deck`。客户端 `BUTTON_HP_READY` 会调用 `LoadCurrentDeck(...)` 后发送 `SendUpdateDeck(...)`；下拉选择与已提交构筑应分别建模。不要为了读取自动点击“准备”或发送联网操作。

## 可继续使用的代码和证据

- 正式基础设施：[`src/trainer/ygopro_capture.py`](../src/trainer/ygopro_capture.py)，包含镜像指纹、进程身份、只读句柄、模块基址、边界及快照一致性校验。
- 本地研究脚本：`.local/probe-duel-deck.py`、`.local/probe-own-duel-zones.py`，以及最初的 `.local/probe-live-deck.py`。这些是针对本机路径的诊断脚本，保留在本地，不作为产品 API。
- 本地证据：`.local/ygopro-live-capture-20260917/evidence/duel-probe.json`、`own-hand-probe.json`，以及三轮真实验收结果。包含个人卡组及进程信息，不纳入 Git。
- 客户端源码参照（本地副本）：`.local/upstream/gframe/deck.h`、`deck_manager.h`、`deck_con.h`、`client_field.h`、`client_card.h`、`menu_handler.cpp` 和 `duelclient.cpp`。部分源码为 Lite 工作副本；实际偏移以匹配指纹的可执行文件和实测结果为准。

后续建议先建立独立的“本局构筑／我方已知区域”快照接口，再验证视角和对局生命周期；保持现有编辑器捕捉入口的语义不变。对局中的稳定快照还需要在读取前后核对区域容器及相关状态，逐项覆盖卡牌移动、抽牌、展开、断线及换副等场景。
