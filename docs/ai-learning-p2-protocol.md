# AI 学习 P2 小试协议

本协议在任何教师执行前冻结 200 个起手家族、划分、场景、结构目标和随机条件。它只用于小试，不证明胜率、已验证康数量，或模型已学会展开。分组不读取教师结果、学生结果或任何 holdout 轨迹。

## 冻结来源与排除

构筑固定为公开 `.local/ygo-agent-pilot/TenyiSword.ydk`，必须与 `experiments/ygo_agent/assets.lock.json` 中的 `85b9b2dda4a24d3d6cd19e335d7a76d533dc3eca910fe3f09d9bc357a5c3ecce` 一致。构建器复用 `experiments.ygo_agent.run.read_deck`，不读取用户牌组或其他私有目录。

起手先按卡号升序规范化；同一多重集的排列不会变成新家族，重复卡的数量仍保留。下列已用公开实验的起手全局排除：

- 原 POC 三局对应的两个起手多重集，来源是 `experiments/ygo_agent/run.py`。
- 所有 `.local/ygo-learning/p0b-p1/data-v2-*/manifest.json` 中的 `source_hands`；清单中的每个 `source_files` 哈希也必须与当前文件一致。
- 所有 `.local/ygo-learning/p0b-p1/development-*/manifest.json` 的 `hands`，包括早期不完整开发运行已经使用的起手。
- 最新一份通过且包含 60 个机制案例、5 个示范的 P1 发布报告所精确引用的 65 个文件。若记录有 `steps`，从第一步 `before.state.cards` 中取我方手牌作为初始起手；缺失或未知的我方卡号会导致构建失败，不会静默略过。

`data-v2` 的历史 `source_hands` 长度不全是 5；它们按原多重集记录来源，只有与 5 张候选起手相同时才会发生排除。这是旧数据的明确解释，不把短前缀扩张为大量未见起手。

协议的 `provenance` 记录构筑、锁文件、清单、发布报告及被引用证据的 SHA-256。缺少文件、JSON 结构错误、记录数不符或哈希改变均会失败。

## 分层与划分

采样种子固定为 `20260920`。候选是主卡组中所有可实现的 5 张多重集，排除已用起手后，用 `SHA-256(seed, scenario, normalized hand)` 给候选产生稳定顺序。较窄的结构条件先选，再选两个不限起手的响应场景，从而保证 200 个起手在全局唯一。

| 场景 | 预先固定的起手或执行条件 | 主目标的额外要求 |
| --- | --- | --- |
| `no_extra_response` | 对手不做额外响应；起手无额外过滤 | 通用结构目标 |
| `one_ash` | 对手最多执行一次明确的灰流丽响应；起手无额外过滤 | 通用结构目标；不声称固定起手必然有可被无效的窗口 |
| `resource_tight` | 起手中资源入口 ID `20001443, 55273560, 56495147, 93490856` 的总张数恰好为 1 | 通用结构目标 |
| `actual_draw` | 起手含 `20001443`，另有一张公开 ID 集 `14821890, 20001443, 23431858, 56465981, 56495147, 87052196, 93490856, 93850690, 98159737` 中的可公开判定展示资源 | 第一回合原生日志必须实际观测到至少一次 `MSG_DRAW`；不从手牌变多推断 |
| `preserve_resources` | 起手至少有两张公开保留资源 ID `10045474, 14558127, 23434538, 24224830, 27204311, 97268402` | 结束时至少保留 2 张手牌 |

五类是起手全局不重复的独立分层。`no_extra_response` 和 `one_ash` 使用不同起手，不构成“同一起手有无灰流丽”的配对因果试验，也不能从两类的差异推断灰流丽的因果效应。本轮 B1/T0 成对比较只在同一家族内进行，共享起手和完整扩展随机条件；以后若从家族派生其他变体，变体仍必须继承原家族的划分。

每类 40 个家族，固定为 24 `train` / 8 `validation` / 8 `holdout`，总计 120 / 40 / 40。每类前 4 个训练家族是教师标定集，总计 20 个。同一家族的变体、分支、重放、排列和增强数据必须沿用家族划分，不得跨集合。

不可能完成的资源场景仍在分母内；不会根据教师成功、得分或轨迹长度事后剔除。

## 随机条件与成对运行

所有家族的原生引擎种子固定为 `42`，这与隔离 `test_control` 实例的当前实现一致。起手之后的剩余牌序由现有 `draw_opening` 在首次运行中均匀生成一次；在 B1/T0 成对比较前保存其摘要，但不向策略输入未知牌序。同一家族的对照、失败重试和分支重放使用应用已有 retry API 保留的完全相同扩展，不再抽一个更有利的牌序。

## 结构目标与判定时点

通用主目标是：我方第一回合已完成，场上至少有 1 张正面、未无效、原始卡号属于冻结公开额外卡组同调集合的我方怪兽，且手牌至少保留 1 张。同调原始 ID 集合为 `5041348, 9464441, 42632209, 43202238, 47710198, 60465049, 69248256, 83755611, 84815190, 96633955`。

这是结构目标，不声称终场已验证可用康、可用无效次数、胜率或最优性。`disabled=false` 只证明精确结算边界的动态无效标志未置位，不代替费用、次数、互斥和真实对手响应验证。

判定使用原生日志中第一个 `turn > 1` 的 batch，也就是第二回合刚开始、对手尚未行动的精确状态。运行器只组装玩家可见的 `p2_goal_card_view_v1`：

```json
{
  "schema": "p2_goal_card_view_v1",
  "cards": [
    {
      "controller": 0,
      "location": 4,
      "position": 1,
      "identity_known": true,
      "code": 69248256,
      "disabled": false
    }
  ]
}
```

判定不需要原生 prompt、实例 ID、未知牌序或过期的动态特征查询。它使用冻结原始卡号成员资格、表示形式和 `disabled` 标志。`completed` 必须由上述第二回合边界证明；`actual_draw_count` 只统计第一回合真实原生 `MSG_DRAW`。结构缺失、未知我方身份、怪兽位置/表示/`disabled` 缺失、未完成边界或负抽牌计数都失败关闭，不做有利推断。

`evaluate_goal()` 返回以下向量及 `success`：`completed`、`face_up_enabled_synchro`、`retained_hand_cards`、`actual_draw_count`。`actual_draw` 场景额外要求抽牌计数至少为 1；`preserve_resources` 场景把手牌门槛提高到 2。

## 产物、校验与 API

完整分组只保存在 `.local/ygo-learning/p2-p3/protocol.json`。`create_protocol(output)` 使用排他创建；路径已存在时，必须先通过 `load_protocol()` 的结构和指纹校验，再与当前冻结来源重建结果逐项相等，否则拒绝复用或覆盖。

稳定 API：

- `build_protocol(deck, exclusions, provenance, *, sampling_seed, code_hash) -> dict`：独立单元测试和内存构建，不需要原生运行时。
- `create_protocol(output: Path) -> dict`：验证公开资产和 P1 来源后排他写入。
- `load_protocol(path: Path) -> dict`：验证 SHA-256 指纹、200 家族、分层/划分、起手可实现性、目标、标定 ID 和随机条件。
- `calibration_families(protocol) -> list`：按冻结顺序返回 20 个训练标定家族的副本。
- `evaluate_goal(card_view, goal, *, completed: bool, actual_draw_count: int) -> dict`：返回结构向量和布尔成功值，未知或不完整数据失败关闭。

`fingerprint` 是除自身字段外的规范 JSON SHA-256；`code_sha256` 固定实际构建这份协议的 `protocol_p2.py`。公开文档和后续报告只发布汇总数和哈希，不打印或公开具体训练、验证及 holdout 起手。
