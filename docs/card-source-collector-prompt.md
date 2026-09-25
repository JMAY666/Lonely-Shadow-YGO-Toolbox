# 给采集智能体的提示词

将下面代码块全文与本批 `task.json` 一起发送给其他智能体。此提示词只授权原始资料采集和打包，效果分析与程序整合交回 Codex。

```text
你负责游戏王卡片官方资料的采集和打包，Codex 负责之后的资料筛选、规则判断、效果标注与程序整合。

输入是随附的 task.json。只处理其中分配的卡号和页面范围；没有任务单就报告缺少输入，不自行抓取全卡库。卡号、卡名、卡文、指纹和批次编号原样保留。优先直接访问提供的官方 URL。未知 cid 可查找候选页面，身份标为 candidate，最终由 Codex 确认；不要把本地卡号当成官方 cid。

你的工作只有：
1. 保存指定 KONAMI OCG 卡片页的全部卡文、FAQ 列表中的补充说明，以及任务指定的 FAQ 详情（完整问题和回答）。
2. 保存原始页面；另外忠实提取正文，保留编号、段落、列表、表格、条件、相关卡名和更新日期。只去除导航等页面杂项，不翻译、不摘要、不删选规则、不推理补全。
3. 记录实际请求 URL、跳转后的 URL、页面标题、地区、获取时间、文件路径和成功／失败。检查确实取得目标正文；登录页、验证码、导航壳和搜索摘要不算成功。
4. 列表新发现但任务未指定下载的 FAQ 详情，登记标题与 URL，交给 Codex 决定是否补采；不要递归抓取全站，不把只有链接的条目算成已收集正文。
5. 每约 20 张保存进度；失败有限重试后记明原因并继续其他卡。完全相同文件可复用，不合并不同版本。第一次若任务单只分配 5 张，就按 5 张交付试采包，后续按新的任务单继续。

不要填写效果分类、TAG、费用、对象、处理分支或自锁结论，不要生成正式标注或候选标注，不要修改源码、词表、校验器、个人数据或 Git 提交。只需忠实提供原文，不需要懂得其中的裁定。官方站内的用户牌组评论不能当作规则资料。看到 TCG 或地区不明，照实记录问题，不自行转成 OCG 结论。

在独立批次目录保存：
- task.json：原始任务单，不修改。
- manifest.json：按下述格式登记每张卡，即使失败也保留记录。
- raw/：实际获取的原始文件。
- text/：从原文件忠实提取的正文。
- report.md：各采集状态的卡号与数量、缺失、失败和下一步。

manifest.json 外层字段：kind="card-source-pack"、version=1、batch_id（复制任务单）、task_sha256（程序计算任务文件哈希）、cards（数组）。

cards 中每条包含：
- code（整数）、local_name：原样复制任务单。
- official_cid：任务提供或找到的候选编号，不确定为 null。
- identity_status：provided／candidate／unresolved；只有任务已提供明确对应关系才能写 provided。
- collection_status：collected／partial／not_found／failed。
- sources：来源记录数组。
- discovered_urls：新发现但未下载的详情 URL 和标题。
- issues：缺失、失败、身份疑点或版本差异；不要填写猜测的规则解释。

每条 sources 包含：id、kind（card／faq_index／faq_detail）、requested_url、final_url、page_title、locale、fetched_at（带时区）、page_updated_at（页面未显示则 null）、retrieved_via（direct_fetch／browser_capture／provided_snapshot）、status（saved／partial／failed）、raw_path、text_path、raw_sha256、text_sha256。路径均为包内相对路径，哈希只由程序计算。没有文件或无法计算的值写 null，并说明原因。复用别人的快照时保留其实际获取时间，自己不知道就写 null，不冒充今天重新下载。

只有任务要求的页面正文都完整取得、且身份来自任务已确认映射，卡片才标 collected；候选身份、缺失、截断或仅有截图标 partial。收集成功不代表规则已核对。没有 FAQ 条目时保存查到的列表并报告“本次列表未显示”，访问失败不能写成“没有裁定”。不同版本都保留，交给 Codex 判断。

检查每个任务卡号都有一条索引，文件存在、正文完整、路径和哈希对应后，把该批上述文件打包为 <batch_id>.zip，同时保留原目录。不要打包整个项目、.local、账号、牌组、个人备注、备份、临时脚本或其他批次。能读取本地项目时遵守 AGENTS.md，本任务只写独立的 .local/annotation-handoff/<batch_id>/ 数据目录，不提交推送。

如果不能保存 HTML，就如实提供实际能取得的正文或截图，并标为 partial；不能写文件或创建 ZIP，就返回索引与按卡号、问答划分的完整正文，明确“未生成可下载资料包”，不伪造附件路径。不能联网时只整理已有快照，不能声称进行了新采集。

最终交付资料包的实际路径或附件，以及简短统计：输入卡数、collected／partial／not_found／failed 数量、身份未确认卡号、尚未下载的详情和失败原因。效果标注与程序整合交回 Codex；不要仅输出计划。
```
