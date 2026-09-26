# 卡片批次整理、续接与检查

用户于2026-09-26确认采用统一批次工具、资料复用、按机制整理、提前登记模型缺口，以及分开检查批次和发布阶段的方法。正式目标仍是处理当前启用卡库的全部可核实非衍生物；本工具处理重复的准备、组装、检查和合并工作。身份候选、来源可读、自动模板和机械验证通过不能代替逐卡规则审核。

## 目录与续接状态

入口为 `python -X utf8 scripts/annotation_pipeline.py`。固定输入、模板、忠实全文包、候选、断点、缓存和备份均写入 `.local/annotation-pipeline/<批次名>/`。原始采集包不改写，不执行包内代码；不写真实用户的个人运行数据。

批次保存 `task.json`、`templates.json`、`schema-outline.json` 和 `ledger.json`。状态依次为准备、组装、验证和合并；已准备、逐卡审核通过、具体原因待核实和实际合并数量分别统计。`status`只读取上次断点，不能代替新检查。

```powershell
python -X utf8 scripts/annotation_pipeline.py status --batch fast-series-01
```

## 1. 冻结完整清单，提前检查结构需求

按真实 `Catalog`和完整系列成员生成输入；已审核且卡文未变的条目跳过，同卡多系列只计一次，异画本地卡号分别保留。缺来源和已有标注冲突会明确登记；完整系列不按数量截断。

```powershell
python -X utf8 scripts/annotation_pipeline.py prepare --batch fast-series-01 --runtime .local/YGOPro-Lite --source-pack .local/annotation-handoff/20260925-catalog-all-14981 --series set:48 set:8 set:7b
```

也可用 `--codes <卡号...>`指定卡号，或用 `--all-remaining`冻结全部剩余卡。未确认身份的来源仍为候选，不能因采集状态为`saved`就确认；已有同名批次不能覆盖，继续工作时用原断点。

`schema-outline.json`按卡片类型、分段数量和灵摆／怪兽区块分组，并列出当前词表，供提前阅读和发现表达缺口。它不推断效果机制；阅读后把明确缺口登记为 `requires_schema`、`requires_vocabulary`或`needs_ruling`，再继续其余卡片。

## 2. 并行准备忠实全文

`packet`用4个线程执行独立的来源读取与哈希检查，保存指定卡号所有已保存来源的完整提取文本及原始元数据。来源包状态不等于“已阅读”或“已核实”。

```powershell
python -X utf8 scripts/annotation_pipeline.py packet --batch fast-series-01 --codes <本批卡号...>
```

来源路径必须留在资料包内；实际原始HTML和正文SHA-256均须匹配。工具不翻译、摘要、删减或补写规则。身份与规则审核由主Agent进行；只负责资料准备的采集者不能填写效果结论。

## 3. 逐卡审核，用数据片段代替重复脚本

复制`templates.json`为本地`decisions.json`，不要修改固定的`task.json`。模板初始为`draft/auto`，含全部真实分段。按相同机制集中阅读和填写，每张卡的费用、时点、对象、处理顺序、限制和次数仍分别核对。

`cards`使用本地整数卡号的字符串键。可以填写完整规范条目，也可以省略工具能从固定输入取得的卡号、冻结卡文、指纹和分段元数据，以分段键到效果数据的字典填写`effects`。用`source_ids`列出实际阅读的日本KONAMI OCG来源；其他证据提供完整`sources`及明确的地区、补采绑定，不能自动改写为日本来源。引用、备注、分类、TAG和效果结构由审核者给出。

只有逐卡判断完成后，审核者才能明确填写`review.status=reviewed`、`review.origin=manual`、日期与依据；工具不会自动升格。效果编号和区块来自实际`segments()`。缺段、自动状态、指纹不符或已有条目冲突会被拒绝。

`pending`填写`code/status/reason`；状态为`not_yet_reviewed`、`needs_ruling`、`requires_schema`、`requires_vocabulary`、`identity_problem`或`missing_sources`。未阅读与证据不足分开，一张卡不能同时已审核和待核实。

`query_cases`、`semantic_cases`和`purpose_cases`沿用[现有批次检查格式](../scripts/check_annotation_source_batch.py)。机制检查必须含有意义的正反例，不能只检查数量。补采用`source_bindings`绑定，不通过改写原包掩盖错配。原包cid为身份候选；纠错时通过`--reviewed-manifest`提供明确核实的cid、来源绑定和查询契约，不只换来源链接而保留错误身份。

```powershell
python -X utf8 scripts/annotation_pipeline.py assemble --batch fast-series-01 --decisions .local/annotation-pipeline/fast-series-01/decisions.json
python -X utf8 scripts/annotation_pipeline.py verify --batch fast-series-01
```

`assemble`只生成私有候选和批次清单。每约20张保存决策、重新组装并检查；未阅读的卡继续待核实，不因一个小检查点就结束完整批次。已有审核输出可用`--reviewed-manifest`配合原公开清单回放；采集结果或旧自动候选不能当作新的人工审核。

## 4. 复用机械检查结果，最终完整复查

缓存指纹含候选数据、公开清单、实际全部卡库记录、系列词表、应用及检查器代码、受控词表和实际来源内容。每次仍重新读取来源字节、计算SHA-256，不只信大小或修改时间。相关内容变化就失效；缓存缺失或损坏则完整重跑。它不监测官网的远端更新；逐卡审核中仍按需要重查当前官方页面，取得新版原文后使用新包或明确补采绑定，不能靠旧缓存宣称官网没有变化。

```powershell
python -X utf8 scripts/annotation_pipeline.py verify --batch fast-series-01 --full
```

`--full`始终重跑结构、卡文、来源、规则边界与真实查询。缓存命中不表示重新完成语义审核。旧检查器的参数与默认完整检查保持兼容；新增`--document`验证候选、`--cache`复用检查点、`--full`强制重跑。

## 5. 完整阶段发布，保留备份和并发检查

纯数据且机制稳定时，默认以约300～500张组成发布阶段；完整系列边界优先，不为凑数接纳不确定卡。约20张的检查继续执行。公共模型、校验器或界面改变时补跑相关检查，不能等待大批结束才发现共用协议错误。

完整清单逐卡处理后，具体证据缺口可暂缓；仍有`not_yet_reviewed`或没有已审核条目时禁止合并。合并强制完整复查，备份旧文档，检查其仍与组装基线一致，拒绝覆盖无关修改或不同公开清单。发布锁异常时先检查原进程和断点，不能盲目删除锁。

```powershell
python -X utf8 scripts/annotation_pipeline.py apply --batch fast-series-01 --public-manifest docs/card-annotation-batch-fast-series-01.json
```

写入失败时原文档或备份保留；重试可完成中断操作，重复合并不会重复新增。已有标注内容不同的修正另走明确修正审核流程，不能悄悄覆盖。

合并后仍按`AGENTS.md`运行全库及系列检查、完整`npm test`、后台开发版和当期打包验收，核对README，审核隐私和全部待推送历史，明确路径提交推送。小检查点不构建安装包，完整发布阶段统一构建当前源码包；真实修复需要重建时如实记录。

## 本轮范围

回放现有95张已审核通常陷阱和5张待核实卡，不增加正式覆盖；原2,488条和查询结果保留。另冻结No.、英雄、银河三个完整系列的386张剩余卡：362张有原包卡页候选，24张缺卡页来源；它们尚未完成规则审核。计时仅表示检查环节，不能外推全库任务的加速倍数。结果见[本轮验证](verification-annotation-pipeline-2026-09-26.md)。
