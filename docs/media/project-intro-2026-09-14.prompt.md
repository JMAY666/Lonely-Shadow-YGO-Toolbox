# 游戏王工具箱介绍图

文件：[project-intro-2026-09-14.png](project-intro-2026-09-14.png)

用于向朋友介绍项目的竖版图片，使用内置 imagegen 生成。场地和一图流画面取自项目现有截图，经过生成式合成，属于功能展示示例，不作为原始截图或规则验收证据。两幅画面来自不同展开实例。

图片尺寸为 1024 × 1536。已人工检查标题、四项功能描述与文字边界，并核对图片可读取、复制前后 SHA-256 一致。功能说明对照当前 README 与界面源码；本次只新增图片和本文，不修改 README、忽略规则或应用行为，也不运行应用测试。

参考画面留在本地，未随介绍图提交：

- `.local/evidence/electron-development/embedded-board.png`
- `.local/evidence/plan-library/live-tutorial-fixed.png`

## 最终生成提示词

```text
Use case: ads-marketing / compositing.
Edit and composite the two supplied application images into ONE finished Chinese product introduction poster for the user's own desktop project, 游戏王工具箱. Portrait 2:3, approximately 1536 by 2304, crisp high-resolution typography, readable when shared on a phone.

Input images:
1. A real YGOPro training-field capture from this project. Use a clean crop of the game board and hand as the main screenshot inset; preserve the card imagery and visible field faithfully.
2. A real screenshot of the project's current illustrated route export preview. Use its connected card-image step panels as a secondary light-colored inset, including the sense of step arrows and "导出 PNG / 导出 SVG". It is a different example from image 1; do not fabricate a shared card sequence linking the two examples. Remove the surrounding dim app background and scrollbar by cropping. Retain actual UI content where legible; do not generate new buttons or claimed functions.

Art direction: professional, restrained game-tool introduction, dark blue-green background matching the app, warm white large type and pale lime-green accents. Flat editorial layout with subtle thin field-grid details, generous negative space, crisp rectangular panels with slightly rounded corners. No glossy sci-fi chrome, no explosion effects, no human characters, no fake laptop or phone. Hero imagery should occupy roughly 45 percent of the poster: main field screenshot above, the light route-export panel overlapping its lower right edge, tidy depth and soft shadows. Both must remain recognizable as the supplied software. Small caption next to the collage, exactly: "场地与一图流示例".

Text and layout, render the following Chinese exactly with no extra claims:
Top small identifier: "YGO TRAINER"
Very large main title: "游戏王工具箱"
Under title, two balanced lines:
"练习展开，记录过程"
"把路线保存下来，回看或分享"

Below the hero collage, a clean two-by-two grid of FOUR numbered feature blocks. Large heading and one readable line in each:
"01  设置起手"
"导入卡组，自定义起手条件"
"02  实际展开"
"手动操作，记录展开过程"
"03  逐步回看"
"查看场面，补充步骤说明"
"04  一图分享"
"保存方案，导出展开图"

Bottom compact line:
"Windows 桌面工具 · 本地保存 · PNG / SVG 导出"

Use modern clean Chinese sans serif typography, strong visual hierarchy, ample margins. Do not repeat the title or add prose paragraphs. No QR code, URL, pricing, download badge, testimonials, unsupported AI claims, automatic combo solving, competitive advantage claims, official publisher logos, or fabricated version numbers. This is an independently developed tool intro. Keep copy grounded in exactly the listed manual practice, recording, review and export features. Deliver the poster itself edge to edge, not a photo of a poster.
```
