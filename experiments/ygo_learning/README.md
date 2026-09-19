# 游戏王学生训练与规则引擎闭环验证

本目录包含独立训练环境、小样本验收和 P0B/P1 规则引擎实验，不参与正式桌面打包。游戏王决策网络在本机 AMD GPU 上训练，导出后由独立 CPU 进程返回动作。这里训练的是新建的小型动作排序学生，**没有继续训练或转换旧 `0546_26550M.tflite` 权重**。

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
