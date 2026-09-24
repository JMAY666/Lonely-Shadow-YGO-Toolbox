# 系列标识制作流程与智能体交接

适用版本：1.47.1；首次样例核对：2026-09-24。先读项目 `AGENTS.md`。本任务维护静态展示资料；已有 46 张效果标注保持独立，原卡库、个人 TAG、备注和备份均保留。

## 已完成的样例

| 系列目录（官方简体中文） | 保留的常用别名 | 系列 ID / 徽记 | 代表卡号与本地卡名 | 来源 |
| --- | --- | --- | --- | --- |
| 青眼 | Blue-Eyes | `set:dd` / 龙眼 / 冰蓝 | `89631139` 青眼白龙；`23995346` 青眼究极龙（融合） | [青眼白龙](https://www.db.yugioh-card.com/yugiohdb/card_search.action?cid=4007&ope=2&request_locale=cn)、[青眼究极龙](https://www.db.yugioh-card.com/yugiohdb/card_search.action?cid=4386&ope=2&request_locale=cn) |
| 转生炎兽 | Salamangreat | `set:119` / 火焰 / 橙红 | `14812471` 转生炎兽 烽火猞猁（连接） | [官方中文卡页](https://www.db.yugioh-card.com/yugiohdb/card_search.action?cid=14249&ope=2&request_locale=cn) |
| 相剑 | Swordsoul | `set:16b` / 双剑 / 青绿 | `69248256` 相剑大师-赤霄（同调） | [官方中文卡页](https://www.db.yugioh-card.com/yugiohdb/card_search.action?cid=16527&ope=2&request_locale=cn) |
| 驱魔姐妹 | 救祓少女、Exosister | `set:172` / 光环 / 紫色 | `42741437` 救祓少女·米迦埃莉丝（超量） | [官方中文「驱魔姐妹・米迦以利斯」](https://www.db.yugioh-card.com/yugiohdb/card_search.action?cid=16740&ope=2&request_locale=cn) |
| 杀手旋律 | 杀手级调整曲、Kewl Tune | `set:1d5` / 波形 / 粉色 | `16387555` 杀手级调整曲·提示员（调整）；`42781164` 杀手级调整曲·音轨制作人（同调／调整） | [官方中文「杀手旋律・绮悠」](https://www.db.yugioh-card.com/yugiohdb/card_search.action?cid=21956&ope=2&request_locale=cn)、[音轨制作人日文页](https://www.db.yugioh-card.com/yugiohdb/card_search.action?cid=21957&ope=2&request_locale=ja) |

以上核对的是系列命名、这七张代表卡的系列身份与类型。徽记为项目自行绘制的 SVG 识别图形，不称为官方徽标。系列中的其他卡依当前卡库自动显示同一徽记，不因此变成逐卡审核完成。青眼究极龙的展示样例也不计为新增完整效果标注。

## 一批资料的制作步骤

1. 读取实际卡库与当前 `annotation-series.json`，按整数卡号定位卡片。记录卡名、`type`、完整 `setcode`；四个 16 位系列编号可能打包在一个有符号 64 位整数中，必须在 Python 中处理，不能让 JavaScript Number 拆这个整数。系列 ID 用稳定的十六进制 `set:…`，不使用卡名作身份。
2. 联网核对 KONAMI 官方 OCG 卡页。优先 `request_locale=cn` 获取官方简体中文系列名；确认页面实际有卡片内容，不能把「Card information not found」或用户牌组名称当成官方译名。保留本地旧译、日文和英文系列名为别名。当前样例均有官方中文；没有官方中文依据的新系列先保留卡库译名与普通文件夹，另记录待核对事项，不伪装为已核对条目。
3. 核对实际系列归属。卡名含某词、卡文检索某系列、官方页面列为「相关卡」均不能单独证明归属。展示层只使用 CDB `setcode`，保留既有父／子系列匹配逻辑。发现官方与本地卡库不一致，记录差异并保持待核对；不要通过个人 TAG 加入卡片来绕过系列依据，也不要改动引擎卡库。
4. 为每个系列挑选至少一张能识别主题的代表卡，并保存来源 URL、标题、地区语言、核对日期和本地类型／系列编号快照。多系列卡可在多个文件夹出现。无编号卡单独归类；有未知编号的卡保留待译名文件夹。
5. 编辑 `src/trainer/annotation-series.json`，沿用现有结构：`id/setcode/name/aliases/emblem/tone/cover_code/sources/samples`。`cover_code` 必须是当前系列中的一张已核对代表样例。`samples[].source_refs` 指向本系列的 `sources[].id`。来源与本地卡号由人工确认，KONAMI `cid` 不能当作游戏内卡号。
6. 复用五种基础色之一或补充有对比度的新色。需要新徽记时，在 `src/trainer/web/card-annotations.js` 的 `annoEmblems` 添加 24×24 的本地 SVG 路径，并在 `card_series.py` 的 `EMBLEMS` 登记；新色同步登记 `TONES` 和 CSS。徽记在 18px 和 34px 下仍应清晰，不能只靠颜色区别。来源数据不得携带任意 SVG/HTML，禁止嵌入脚本、外链图片或事件属性。
7. 封面走现有本地 `/pics/<卡号>.jpg` 服务，普通文件夹自动选代表图。原图缺失显示应用卡背，加载失败保留文件夹图形。不要把本机完整卡图集、下载缓存、测试截图或个人资料提交到 Git；本批没有另行下载卡图。未来新增外部素材时，先记录其来源与允许的用途。
8. 不为每张卡重复编写效果颜色或怪兽类型。效果 TAG 颜色由既有八类 `category` 决定；保留标签 ID、文字、定义。类型直接读取 `type`：`0x40` 融合 `∞`，`0x2000` 同调 `✧`，`0x800000` 超量 `◎`，`0x4000000` 连接 `↗`；`0x1000000` 灵摆 `◈`、`0x1000` 调整 `♪` 为附加标识，`0x80` 仪式 `◇` 不算额外卡组类型。魔法／陷阱不能显示怪兽类型符号。
9. 运行下面的校验，再在后台桌面测试中查一次旧译名、打开一个系列、点击右上角原图浮层并关闭、验证缩略图、符号与效果颜色，检查 760px 窄窗口。按项目约定审核、提交并推送；交付完成卡号、系列、来源和未解决差异。

```powershell
python scripts/check_annotation_series.py --runtime .local/YGOPro-Lite
python scripts/check_card_annotations.py --runtime .local/YGOPro-Lite
python -m unittest discover -s tests -p test_card_series.py -q
python -m unittest discover -s tests -p test_card_annotations.py -q
node --test tests/card_annotations_view.test.cjs
python -m unittest discover -s tests -p test_card_release_dates.py -q
npm run test:desktop -- --annotations-only
# 更改打包资源后先构建当前版本，再验收包内页面：
npm run build:dir
npm run test:packaged -- --annotations-only
```

只读校验器检查字段、来源引用、徽记登记、封面与当前卡库类型／归属一致；不会替代人工阅读官方来源。数据库重载会重建目录。扩充样例后同步更新 README 与批次记录；不能删除失败断言来掩盖资料差异。

## 发售时间资料与更新

系列排序口径为：当前完整系列成员中，所有已知 OCG／TCG 实体卡首发日期的最小值。区域也随日期记录；这不是数字版上线时间、最近一次再版时间或系列编号的大小，也不保证等于该系列名称被正式定义的日期。两地区取较早者可保留海外先发系列的首次出现时间。未查到日期的系列标记「日期待补」并置后，不以卡号或系列编号代替。未来日期显示「预定」。

2026-09-24 从 [YGOPRODeck 公共 API](https://db.ygoprodeck.com/api/v7/cardinfo.php?misc=yes)取得快照，[字段定义](https://ygoprodeck.com/api-guide/)中的 `ocg_date`、`tcg_date` 表示各地区原始发售日期。本项目只打包 14,487 张卡的日期与 4,086 个来源明确的临时卡号／异画卡号映射（约 0.78 MB），没有复制卡文、图片或价格。原始响应仅留在 `.local/series-release-research/`；SHA256 保存在精简资料的 `source` 中。依赖来源记录，未逐张进行官方审核；日期覆盖率及来源日期可以在文件夹日期提示里查看。

抽查与 KONAMI 日文卡页收录日期一致：[杀手旋律·提示员 2025-08-23](https://www.db.yugioh-card.com/yugiohdb/card_search.action?cid=21956&ope=2&request_locale=ja)、[驱魔姐妹·米迦以利斯 2021-08-28](https://www.db.yugioh-card.com/yugiohdb/card_search.action?cid=16740&ope=2&request_locale=ja)、[转生炎兽 狐狸 2018-07-14](https://www.db.yugioh-card.com/yugiohdb/card_search.action?cid=13890&ope=2&request_locale=ja)。这些仅是抽查，不把全库日期声明为官方逐卡复核完成。

更新时遵守 API 限流，将完整响应缓存到 `.local/`，不要在正常应用启动或每次点击时访问网络。运行 `python scripts/build_card_release_dates.py --input <本地响应.json> --retrieved-on YYYY-MM-DD`，只在数据非空、日期格式合法且无同卡冲突时生成资料。`cards` 各行的两个值依次为 OCG／TCG 日期，空字符串表示该地区未知；`aliases` 只采信来源显式的 `beta_id` 和异画 `card_images[].id`，歧义映射丢弃。不能根据相似卡名、CDB 名称等价或整数接近猜测日期。提交前比较记录数量、检查异常日期、跑日期与系列测试，补充覆盖与缺口记录。

## 可直接交给下一位智能体

> 请按 `docs/card-series-production-guide.md` 为我指定的系列批次补充卡片标注页的官方中文系列名、旧译名检索别名、独特徽记、代表卡封面和逐卡来源。先读取当前卡库与已有五系列七卡样例，再联网核对 KONAMI 卡页；卡库系列编号决定归属，相关卡和效果提及不等于系列成员。完整效果标注另按 `card-annotation-agent-guide.md`，不得把视觉样例数量算成效果审核数量。保留个人 TAG、备注、原卡名和数据备份。按指南完成校验、后台桌面及打包测试，审核后提交推送，并报告本批完成与待核对内容。
