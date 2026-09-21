# 游戏王学生训练与规则引擎闭环验证

本目录包含独立训练环境、小样本验收、P0B/P1 规则引擎实验，以及 P2 分组冻结与 P3 教师标定，不参与正式桌面打包。游戏王决策网络在本机 AMD GPU 上训练，导出后由独立 CPU 进程返回动作。这里训练的是新建的小型动作排序学生，**没有继续训练或转换旧 `0546_26550M.tflite` 权重**。

整体实验范围及后续教师/学生对照见[验证计划](../../docs/ai-learning-feasibility-plan.md)，新的字段定义与拒绝边界见[观察/动作契约 v2](../../docs/ai-learning-contract-v2.md)。下文先保留 P0A 的 78 样本原始结果，再介绍 P1 独立实现；二者不能合并为策略评测。

## 独立环境

- CPython 3.13.13，Windows x64。
- PyTorch `2.12.0+rocm7.14.1`、HIP `7.14.60850`、NumPy `2.4.4`。
- 通过 AMD 官方包索引安装 `gfx1201` 专用依赖；18 个包的实际版本见[锁定文件](requirements-rocm-windows.lock.txt)。直接依赖见[依赖声明](requirements-rocm-windows.txt)。
- 解释器位于 `.local/ygo-learning/.venv/Scripts/python.exe`。不替换系统 Python、旧模型试验环境或显卡驱动。
- 本机独显为 RX 9070 XT，PyTorch 枚举为 `cuda:1`；`cuda:0` 是集显。ROCm PyTorch 沿用 `torch.cuda` API 名称，不表示使用 NVIDIA 显卡。运行器每次按实际设备名称选择独显，不依赖固定编号，也不静默回退到 CPU。
- 只在测试进程内设置 `TORCH_BLAS_PREFER_HIPBLASLT=0`，依据 [AMD 的 Radeon 训练说明](https://rocm.docs.amd.com/projects/ai-ecosystem/en/latest/frameworks/pytorch/install.html)避开已知的部分 hipBLASLt 训练问题；没有修改系统环境变量。

重新配置时从仓库根目录运行：

```powershell
powershell -NoProfile -File experiments/ygo_learning/setup.ps1
```

这会同步独立虚拟环境内的依赖，不处理其他环境。免费公开依赖需要联网下载，不涉及付费 API 或云 GPU。`uv` 与已有公开模型试验资源是前置条件。

## 真实样本来源

`prepare_smoke_data.py` 只读取 `.local/ygo-agent-pilot/` 内三场公开相剑试验及其明确标记 `test_control=true` 的原生记录。

数据核对包括：固定上游特征代码与模型资产哈希、卡库版本、建议对应的决策窗口、唯一实际响应、后继引擎检查点、微选择与原生响应的一致性。使用已有适配器遮蔽对手未知身份及真实牌序；学生输入不含原始复现种子或完整私有日志。

本轮提取了 89 个引擎已确认的决策窗口，得到 **78 个不同的多选学习样本**；11 个单选窗口保留历史但不纳入策略学习，3 个未执行的结束回合建议被排除。三场来源没有划分独立测试集，这些样本只用于检查能否拟合、是否有梯度及导出是否一致。

原始试验的限制仍然成立：部分动态属性使用卡库基础值、只覆盖部分先攻首回合窗口；本次提取没有重新在完整规则引擎中重放全部对局。当前数据不是已经完成正式训练集审计的产物，拟合结果不代表真实胜率或策略泛化。

重复运行提取器会验证并复用相同的不可变数据；数据或来源变化会报错，保留旧文件。

## 执行检查

```powershell
# 使用原有试验环境读取已固定的特征编码与公开记录。
.local/ygo-agent-pilot/.venv/Scripts/python.exe -X utf8 experiments/ygo_learning/prepare_smoke_data.py

# 在新环境执行 GPU/CPU 对照、训练、恢复及 CPU 导出。
.local/ygo-learning/.venv/Scripts/python.exe -X utf8 experiments/ygo_learning/gpu_smoke.py

# 来源边界、动作身份与合法候选检查。
.local/ygo-learning/.venv/Scripts/python.exe -X utf8 -m unittest discover -s experiments/ygo_learning -p 'test_*.py' -v
```

默认在 GPU、CPU 各执行 200 次全批更新，训练批大小等于样本数。`--steps` 只允许 100–500 次，避免误启动长时间任务。模型采用按字节字段区分的嵌入、局面/历史编码和共享动作评分，保留显式合法动作掩码。

运行器检查：

1. ROCm 后端和独显真实存在，GPU 任务确实分配到独显。
2. 同初值、同数据的 CPU/GPU 首次损失、梯度及参数更新在声明容差内。
3. 每步梯度有限，参数实际变化；小样本损失至少减半，拟合准确率达到 90%。这个门槛只检查训练链路，不衡量实战强度。
4. 保存模型及优化器后恢复，再执行同一个更新，核对参数一致性。
5. 导出动态批次的 `torch.export` CPU 产物，在屏蔽 GPU 的新进程中加载，核对完整批次及单条输入的候选选择。
6. 使用同一份部署权重比较 CPU/GPU 单条输入延迟，包含输入传输和取回动作编号，模型常驻内存；不含游戏引擎和应用 IPC。

## 验收结果

2026-09-19，完整运行 `student-smoke-20260919-114101` 通过。学生有 **1,010,545 个参数**，使用 78 个不同的多选样本；固定种子 19、AdamW、学习率 0.003、`eps=1e-6`、FP32，CPU 四线程。

| 检查 | 实际结果 |
| --- | --- |
| 实际训练设备 | RX 9070 XT，ROCm `cuda:1` |
| CPU/GPU 首次更新对照 | 通过；最大梯度绝对差约 `5.44e-8`，参数仍使用原定容差 |
| GPU 200 次更新 | 约 **1.10 秒**；损失 `1.25286 → 0.000274` |
| CPU 200 次更新 | 约 **60.85 秒**；损失 `1.25286 → 0.000345` |
| 小样本拟合 | GPU、CPU 均为 `78/78`；这是训练内拟合，不是胜率或泛化准确率 |
| 模型与优化器恢复 | 通过；恢复后额外执行一次相同更新并核对参数 |
| CPU 导出 | 通过；在屏蔽 GPU 的新进程加载 `.pt2`，单条/完整批次均与参考动作一致 |
| 单条推理中位数 | CPU **1.08 ms**，GPU **2.08 ms**，同一份部署权重、包含输入/结果传输 |
| PyTorch GPU 内存统计 | 峰值分配约 134 MiB、预留 156 MiB；不包含所有驱动及进程显存开销 |

训练时间包含逐步有限性检查，排除环境启动、模型加载、保存与导出。训练批次较小且固定，执行顺序固定，没有进行跨时段重复或大规模吞吐评测；不能把这次约 55.5 倍的训练循环差值推广到其他模型/批次。单条推理只做 10 次预热、30 次计时，不含游戏引擎和应用 IPC。本轮更适合采用 **GPU 训练、CPU 单条推理**。

另通过 6 项新来源/候选检查、原有模型试验的 13 项边界检查、18 个依赖包的兼容检查，以及安装脚本的重复执行检查。正式应用源码未改动，未运行桌面或打包验收，也没有进行学生在真实引擎中的独立对局评测。

实际报告与部署产物：

- `.local/ygo-learning/student-smoke-20260919-114101/report.json`
- `.local/ygo-learning/student-smoke-20260919-114101/student-checkpoint.pt`
- `.local/ygo-learning/student-smoke-20260919-114101/student-cpu.pt2`
- `.local/ygo-learning/smoke-data/manifest.json`

开发过程已经记录：默认 AdamW 的微小梯度数值差异导致首次更新容差失败；保持检查容差不变，改用 `eps=1e-6`。直接把类别字节统一当连续值的初版学生，200/500 步拟合分别未通过；改用字段嵌入后重新检查。旧失败报告保留，不覆盖。

导出阶段另遇到原生文件写入器不接受中文路径的问题，已使用内存缓冲区和 Python 文件读写完成保存/加载，并通过独立 CPU 进程验证。导出时出现未安装 Triton 的 FLOP 统计提示，以及 MIOpen 不支持 cuDNN benchmark limit 的提示；本试验未使用 Triton FLOP 计数或卷积性能调优，实际训练及导出检查均通过，没有为消除提示安装额外框架。

## 本地文件与范围

虚拟环境、数据、权重、CPU 导出和 JSON 报告均位于 `.local/ygo-learning/`，沿用现有忽略规则。每次运行创建单独的 `student-smoke-*` 目录，保存源码副本和哈希，以便核对被测试的版本。旧 POC 模型、证据和正式用户数据保持原样。

上述 P0A 探针没有新增应用按钮或进行实际对局评测。动态局面与连续执行由下述 P1 单独验收；正式数据划分、教师质量和未见局面的策略评测仍属于后续阶段。

## P0B/P1：独立执行器和数据契约

`desktop_p1.cjs` 创建隐藏的 Electron 验收实例，通过内部训练接口运行真实核心。它使用 `.local/ygo-learning/p0b-p1/`，要求测试控制与学习模式同时启用，保留有意义的连锁窗口；没有全局键鼠输入，也不操作正式用户对局。

| 文件 | 职责 |
| --- | --- |
| `contract_v2.py` | 玩家可见的动态状态、容量校验、完整响应候选、模型特征 |
| `native_session.py` / `confirmed_history.py` | 同一窗口的租约提交、精确回执、后继状态与已执行历史恢复 |
| `mechanisms.py` | 12 类各 5 个真实机制案例，以及 5 场受控相剑开发示范 |
| `export_v2.py` / `train_v2.py` | 只从确认过的开发示范生成训练数据；GPU 训练、恢复与 CPU 导出 |
| `policy_client.py` / `policy_worker.py` | 有时限的独立 CPU 进程、版本/形状校验和失败停止 |
| `development.py` | 50 个新起手自行执行，30 个共同窗口的延迟对照，独立记录循环、正常结束与不支持 |
| `journal_audit.py` / `report_p1.py` | 对照原始日志、确认没有跳过有意义的我方选择，核对完整重放与成本 |
| `throughput_compare.py` | 两个隔离引擎的吞吐对照；保留隐藏窗口的渲染开销 |
| `budget.py` / `provenance.py` | 已知进程的内存/磁盘/时间边界、原生规则文件与代码版本绑定 |

从仓库根目录运行以下步骤。引擎需先按项目构建说明编译并执行 `python scripts/prepare_desktop.py`；训练环境继续复用上文已验证的版本。命令中的目录占位符替换为该步骤打印的实际输出，禁止使用正式用户数据。

```powershell
node experiments/ygo_learning/desktop_p1.cjs --suite=mechanisms
node experiments/ygo_learning/desktop_p1.cjs --suite=demonstrations
.local/ygo-agent-pilot/.venv/Scripts/python.exe -X utf8 experiments/ygo_learning/export_v2.py "<机制目录>" "<示范目录>"
.local/ygo-learning/.venv/Scripts/python.exe -X utf8 experiments/ygo_learning/train_v2.py "<数据目录>/data.npz"
.local/ygo-learning/.venv/Scripts/python.exe -X utf8 experiments/ygo_learning/verify_worker_v2.py "<模型目录>" "<数据目录>/data.npz"
node experiments/ygo_learning/desktop_p1.cjs --suite=development --count=50 --model="<模型目录>"
.local/ygo-agent-pilot/.venv/Scripts/python.exe -X utf8 experiments/ygo_learning/throughput_compare.py
.local/ygo-learning/.venv/Scripts/python.exe -X utf8 -m unittest discover -s experiments/ygo_learning -p 'test_*v2.py' -v
```

修复某个机制断言后可通过 `--groups`、`--first-variant` 和 `--variants` 只运行受影响的部分。汇总验收仍要求 60 个互不重复且断言通过的案例，并保留原失败尝试；不能以部分通过的目录声称全套成功。

新学生为 1,466,609 参数，本轮开发数据含 423 个多选决策。RX 9070 XT 完成 400 次全批更新约 6.76 秒，训练内已观察标签集合命中率约 98.35%；CPU/GPU 梯度、优化器恢复、导出动作一致性和新的 CPU 进程检查通过。训练样本来自受控机制和开发示范，标签不表示最优策略；实际连续执行和时间预算以[本轮验收记录](../../docs/ai-learning-p0b-p1-results.md)为准。

模型包拒绝旧契约、变化的代码/规则文件和损坏的部署文件。类型计数器、溢出求和、无法唯一定位的实例或容量溢出等首轮边界明确停止。学生的循环停止不计为完成回合，结束回合请求也必须等到真实回合变更后才计为完成。当前没有 T0/T1 教师生成的正式数据、未见局面策略增益或自动更新/产品接入的验证结论。

## P2/P3：冻结分组与无 LLM 教师标定

2026-09-20 的 [原始标定报告](../../docs/ai-learning-p2-p3-results.md)保留 T0 达标 10/20、B1 达标 13/20 的失败证据。2026-09-21 的纠偏使用独立源码快照及新批次，不覆盖原记录；结果及下一步见[纠偏报告](../../docs/ai-learning-p3-correction-results.md)。重跑继续扣累计预算，不因重新启动而归零。

[P2 小试协议](../../docs/ai-learning-p2-protocol.md)固定 200 个公开构筑起手家族和 120/40/40 划分。每个场景选 4 个训练家族，共 20 个，用于 T0/B1 成对运行；验证与留出家族不执行。原 POC、P1 开发及机制/示范起手按来源哈希排除。首次生成的随机条件登记到本地，后续运行沿原生 retry 链复用，包括失败重试。

| 文件 | 职责 |
| --- | --- |
| `protocol_p2.py` | 划分、来源指纹、排他冻结及结构目标正反例判定 |
| `teacher_p3.py` | 真实前缀的有限搜索；只评分玩家观察；抽牌/随机/私有结果边界停止 |
| `module_proposals.py` | 仅从五场冻结公共示范重新绑定合法动作提案，不读取个人方案库 |
| `calibration_p3.py` | B1/T0 配对执行、累计预算、原生首回合边界、失败和中断证据 |
| `evidence_p3.py` | gzip 与按哈希引用的状态，完整恢复和篡改检查；保留原始证据 |
| `session_archive.py` | 新建测试会话的逐文件无损归档、恢复验证及原始字节的按需恢复 |
| `report_p3.py` / `report_p3_evidence.py` | 核对 20 个完整家族对，兼容原始及归档证据，并外推耗时与实际存储预算 |

复用已有环境，从仓库根目录执行：

```powershell
# 只读取固定公开构筑及过去的公开实验；已存在的协议只能验证复用。
.local/ygo-agent-pilot/.venv/Scripts/python.exe -X utf8 -c "from pathlib import Path; from experiments.ygo_learning.protocol_p2 import create_protocol; p=create_protocol(Path('.local/ygo-learning/p2-p3/protocol.json')); print(p['fingerprint'])"

# 每批 5 个训练家族；每批最多 30 分钟，P2/P3 累计最多 2 小时。
node experiments/ygo_learning/desktop_p1.cjs --suite=teacher --first-family=1 --count=5
node experiments/ygo_learning/desktop_p1.cjs --suite=teacher --first-family=6 --count=5
node experiments/ygo_learning/desktop_p1.cjs --suite=teacher --first-family=11 --count=5
node experiments/ygo_learning/desktop_p1.cjs --suite=teacher --first-family=16 --count=5

# 显式指定上述四个成功完成的批次目录；重复、缺少或混用源码版本会拒绝汇总。
.local/ygo-agent-pilot/.venv/Scripts/python.exe -X utf8 experiments/ygo_learning/report_p3.py "<批次1>" "<批次2>" "<批次3>" "<批次4>"
.local/ygo-learning/.venv/Scripts/python.exe -X utf8 -m unittest discover -s experiments/ygo_learning -p 'test_*.py' -v
```

纠偏配置 `T0-correction-v5` 每次最多 24 个原生决策节点、12 层原生决策、2 秒，束宽 2、每窗展开排序前 3 个候选。检查时限后不再启动新探针，已启动的原生调用可能使墙钟超过 2 秒，实际耗时照实记录。这不表示穷举所有合法动作。

无响应条件显式提交合法 pass/no；一次灰流丽条件沿用预声明的原生简单对手策略，在隔离探针内结算。该条件是预先固定的实验前提，不能用于推断真实未知手牌。唯一合法动作、固定落点/表示形式及唯一完成素材选择的启发式可在探针内连续推进，每次原生响应均计入节点和深度；实际执行仍逐窗确认。回到已执行的策略窗口会剪枝，连续空连锁确认不会误判为策略循环。未知抽牌、随机结果或牌序访问污点仍在构造后继观察、提案或评分前停止。

评分区分同调目标、保留手牌、通常召唤资源，以及当前合法菜单提供的起动效果和同调机会。公共示范仅增加可重新绑定的动作提案，不证明整条路线适用于新起手。选定根响应已在本次搜索中通过相同守卫的探针时，复用这份响应证明；实际回执、独立原生日志及最终完整重放继续检查。

B1 保留旧模型的循环状态，只在实际响应确认后提交历史。B2 仅核对冻结公共 P1 示范的精确起手匹配，由于排除规则，其覆盖为零；不能代表产品全部模块来源的能力。结构目标使用刚进入第 2 回合的原生状态，包含首回合真实抽牌计数，但不证明无效效果仍有费用、次数或互斥可用性。

教师标定不训练学生、不调用本地 LLM、不打开独立留出结果。旧批次的原始 JSON/JSONL、未压缩记录和失败证据继续保留。新批次先保存收集记录，再对已退出且 `test_control=true` 的本次会话制作 ZIP，逐文件核对大小和 SHA-256，完整恢复并重审原生日志后采用紧凑存储。原始字节、重放调用、检查点和全部失败记录均保留在归档中；会话元数据、版本化报告缓存和起手文件留在原处，供隔离应用列表与同条件 retry 使用。原生接口无需更改。

新会话目录中的 `evidence-archive.json` 给出归档位置、哈希与会话身份。`session_archive.restore_archive(archive, destination, expected_hash)` 只恢复到不存在的新目录，拒绝覆盖、路径越界和哈希不符；汇总器自动恢复到 `.local/ygo-learning/p0b-p1/archive-restores/` 下的临时目录并完成审计。这些实验会话的历史时间线或原始日志如需直接从应用打开，应先恢复到独立副本；紧凑存储未接入正式用户历史。

存储预算同时计算 ZIP、收集器 gzip、保留缓存、环境和原有证据，恢复和写入开销也计入批次时间。未通过保守预算前不扩大采样，不能仅用 gzip 或 ZIP 大小代替完整目录成本。

## P3 后续：资源取舍与分项成本

当前配置为 `T0-resource-v7`，结果及保留的失败尝试见[资源与时间优化报告](../../docs/ai-learning-p3-resource-results.md)。它仍只使用同一批 20 个训练家族，协议、划分、目标、B1 和失败分母不变。正式质量以独立验证为准，不能把开发反例上的改进当作泛化收益。

评分补充了可见起动效果在费用/素材及连锁窗口中的潜力，并保留通常召唤机会的价值。搜索保持每窗 24 个原生节点、12 层、2 秒、束宽 2、排序前三个候选；若合法停止动作不在前三个中，再比较该动作，不挤掉原有候选。额外候选及所有微选择都扣同一个节点预算。实际未知随机后继仍在构造观察和评分前停止。

本轮新增原生分项计时，先按项目构建流程更新测试资源：

```powershell
python scripts/apply_lite.py
./scripts/build.ps1
python scripts/prepare_desktop.py

# --fast 仅为隔离学习实例跳过动画等待，仍逐窗提交并保留完整原生事件。
node experiments/ygo_learning/desktop_p1.cjs --suite=teacher --first-family=1 --count=5 --fast
# 后续批次将 first-family 依次改为 6、11、16；累计预算不会重置。
```

`--fast` 同时要求原生测试控制、学习模式与 `YGO_TRAIN_LEARNING_FAST=1`，默认关闭。它不关闭渲染、不绕过合法选择，也不改变正常训练随机性。计时分别保存前缀重建、分支结算、动态快照、请求与读取、实际回答等待、模型/特征、会话结束和归档编码/恢复。通信余量包含文件发布、轮询、解码和调度，不将它全部称为纯 IPC 开销；嵌套时间不能重复相加。

加入原生计时会改变二进制哈希。普通恢复接口继续拒绝跨版本重开；`/api/native/learning-fixture` 只允许固定的本地隔离学习目录，且要求测试控制和学习模式同时开启。它核对关闭状态、固定实验种子、原卡库与脚本，把同一扩展条件导入新会话，记录新旧引擎与来源身份，保留旧记录。该操作本身不证明规则等价，还要核对实际起点、B1 完整响应前缀、终场和完整重放。正常桌面及打包应用都应拒绝此接口。

ZIP 完整恢复时直接进行原生日志审计；收集器 gzip 只解码一次并同时核对内存记录和临时原始 JSON，验证后才移除重复表示。格式仍兼容旧证据，恢复出的共享快照是彼此独立的副本。最终汇总另做独立恢复审计，并将恢复临时空间加入存储门槛。原生与服务实现也随每批实验保存源码哈希及副本。

Windows 短暂占用已验证的重复文件时，进行有限次数重试；仍被占用则保留该文件并计入实际磁盘成本，归档中的原始字节保持可恢复。收尾异常时另存已经收集的逐步轨迹和会话标识。仅在原生进程已退出时，允许从中断测试记录导入完全相同的扩展条件；重新按种子抽起手不能代替原牌序。

### 40 家族验证集

[选择标准](../../docs/ai-learning-p3-validation-protocol.md)在任何验证执行前登记。`validation_p3.py` 检查已审计标定报告、当前空间、剩余累计预算及教师/规则哈希，排他创建 `validation-registration.json`；已有登记只能原样核对复用。运行器只接受 P2 的 40 个 validation 家族，每批最多 5 个，holdout 不可作为参数选择。所有开发、失败重试及验证累计到同一 2 小时账本。

```powershell
node experiments/ygo_learning/desktop_p1.cjs --suite=teacher-validation --first-family=1 --count=5 --fast --calibration-report=.local/ygo-learning/p2-p3/report-20260921-113043/summary.json
# 后续 first-family=6,11,16,21,26,31,36；可靠性失败先修复并保留原尝试。
.local/ygo-agent-pilot/.venv/Scripts/python.exe -X utf8 experiments/ygo_learning/report_p3.py --validation "<最终批次1>" "<最终批次2>" "<最终批次3>" "<最终批次4>" "<最终批次5>" "<最终批次6>" "<最终批次7>" "<最终批次8>"
```

汇总必须覆盖全部 40 对，拒绝混用源码、模式或登记版本。输出配对差值、固定种子的 10,000 次 bootstrap 区间、共同支持范围、成本门槛和是否允许进入 P4。失败或证据不足时保留完整分母与记录，不用验证轨迹训练学生。

本轮实际在 24/40 对完成后因原生焦点事件的锁顺序冲突中止，详见[验证中止与死锁修复](../../docs/ai-learning-p3-validation-results.md)。修复后仅复测两个已知失败家族，各三轮、共 12 次执行均通过；没有拼接成 40 对结论。当前 worker 剩余约 32.82 分钟，小于原保守完整验证预测 45.10 分钟，且旧登记绑定旧原生版本，因此继续停止扩展。

限定恢复诊断命令是 `node experiments/ygo_learning/desktop_p1.cjs --suite=teacher-recovery --first-family=1 --count=2 --fast`，只允许这两个已保存原条件的验证失败家族，不能选择新验证或 holdout。新原生版本、诊断与旧版本部分验证分别保存；下一次完整验证须先登记新的版本/预算方案，不能覆盖原登记或重置累计预算。
