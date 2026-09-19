"""Render only local pilot evidence; no network requests or private deck imports."""
import html
import json
from pathlib import Path
import statistics
import sys
from datetime import date

ROOT = Path(__file__).resolve().parents[2]
LOCAL = ROOT / '.local/ygo-agent-pilot'
sys.path.insert(0, str(ROOT / 'src/trainer'))
from module_conditions import facts_from_report

LABELS = {'baseline': '莫邪＋龙渊起手', 'single-starter': '无龙渊起手', 'ash': '灰流丽干扰'}
LIMITS = [
    '使用现成模型，未训练或微调；少量指定起手案例不构成胜率或最优性评测。',
    '只覆盖相剑的部分先攻决策窗口；模型只识别匹配卡号表中的 864 张卡。',
    '卡牌攻防、等级、种族和类型来自卡库基础值，不是效果改变后的完整动态值。',
    '没有训练样本外的系统性策略对比；当前合法不等于推荐最好。',
    '模型输入隐藏对手未知卡牌，并对自己的剩余牌组去除真实顺序；不读取屏幕进行决策。',
    '固定起手以外的牌序仍由隔离练习生成，具体牌序与实际抽牌保存在本地原生记录中。',
    '正式应用尚未增加助手按钮；测试输入只作用于本次创建且 test_control=true 的后台实例。',
    '仅有一个合法选项时直接采用；耗时统计包含这些不调用神经网络的窗口。',
]


def step_status(step, result):
    if step.get('engine_accepted'): return '引擎已确认'
    if result['status'] == 'model_recommended_end_turn' and step is result['steps'][-1]:
        return '结束回合建议，未执行'
    return '未确认执行'


def main():
    cases = {}
    for path in sorted((LOCAL / 'evidence').glob('*/result.json')):
        result = json.loads(path.read_text(encoding='utf-8'))
        if result.get('case') not in LABELS: continue
        report_path = path.parent / 'report.json'
        report = json.loads(report_path.read_text(encoding='utf-8')) if report_path.exists() else {}
        result['negations'] = [f for f in facts_from_report(report) if 'negated' in f['kind']]
        cases[result['case']] = (path, result)
    if not cases: raise ValueError('No completed pilot evidence found')
    samples = [s['inference_ms'] for _, result in cases.values() for s in result['steps']]
    accepted = sum(bool(s.get('engine_accepted')) for _, result in cases.values() for s in result['steps'])
    end_suggestions = sum(result['status'] == 'model_recommended_end_turn' for _, result in cases.values())
    metrics = {'cases': len(cases), 'recommendations': len(samples), 'native_actions_confirmed': accepted,
               'median_ms': round(statistics.median(samples), 3) if samples else None,
               'min_ms': min(samples) if samples else None, 'max_ms': max(samples) if samples else None}
    timing = f'{metrics["median_ms"]:.2f}' if samples else '—'
    timing_note = (f'特征适配与推理中位耗时 {timing} ms，范围 {min(samples):.2f}–{max(samples):.2f} ms；不含首次加载、界面动画和规则结算。'
                   if samples else '没有成功生成推荐，暂无耗时统计。')
    (LOCAL / 'summary.json').write_text(json.dumps(metrics, indent=2), encoding='utf-8')
    text = ['# ygo-agent 本机逐步指导试验', '',
        '**试验链路：现成模型 → 工具箱合法窗口 → 本局真实操作 → 新局面 → 下一步。**', '',
        '没有调用方案库来生成这些动作。原生引擎负责执行与结算，模型负责从当前可选动作中选取建议。', '',
        f'{metrics["cases"]} 个指定起手案例，共 {accepted} 次操作获得引擎后继状态确认，未执行的结束回合建议：{end_suggestions}。',
        timing_note, '',
        '| 案例 | 已执行选择 | 实际场面 | 干扰证据 |', '| --- | ---: | --- | --- |']
    blocks, details_text = [], []
    for key in LABELS:
        if key not in cases: continue
        path, result = cases[key]
        board = '、'.join(c['name'] for c in result.get('final_board', []) if c['controller'] == 0 and c['location'] in (4, 8)) or '未形成场面'
        n = sum(bool(s.get('engine_accepted')) for s in result['steps'])
        catalog = result.get('source_identity', {}).get('catalog', {})
        interruption = '；'.join(catalog.get(str(f.get('code')), {}).get('name', str(f.get('code'))) +
            ('发动被无效' if f['kind'] == 'activation_negated' else '效果被无效') for f in result['negations']) or '无已记录的效果无效'
        text.append(f'| {LABELS[key]} | {n} | {board} | {interruption} |')
        items = ''.join(f'<li><span>{html.escape(s["label"])}</span><small>{s["inference_ms"]:.2f} ms · '
                        f'{step_status(s, result)}</small></li>' for s in result['steps'])
        source = html.escape(path.relative_to(LOCAL).as_posix())
        status_label = '模型建议结束回合' if result['status'] == 'model_recommended_end_turn' else '试验停止：' + result['status']
        blocks.append(f'<section><div class="eyebrow">{n} 次实际选择 · {html.escape(status_label)}</div>'
            f'<h2>{LABELS[key]}</h2><p class="board">{html.escape(board)}</p><p>{html.escape(interruption)}</p>'
            f'<details><summary>查看逐步建议与确认记录</summary><ol>{items}</ol></details>'
            f'<a href="{source}">原始结果 JSON</a></section>')
        details_text.extend(['', f'## {LABELS[key]}', '', f'状态：{status_label}。', '',
                     f'[原始结果]({path.resolve().as_posix()})', '',
                     *[f'{i}. {s["label"]}（{step_status(s, result)}）' for i, s in enumerate(result['steps'], 1)]])
    text.extend(details_text)
    text.extend(['', '## 判断与边界', '',
        '继续投入应先补齐动态局面与动作覆盖，再与已有路线对比，不能据这些案例认定模型更强。干扰是否发生以原生无效事件为准；场面与逐步建议均来自对应的实际记录。', '',
        *['- ' + item for item in LIMITS], '',
        'Windows x64 / Python 3.14.5 / LiteRT 2.2.0 / CPU 两线程。权重 0546_26550M.tflite，源码与卡号表固定至 7888000e。', '',
        '下载文件、独立环境、测试牌组、原生日志及报告均留在 .local/ygo-agent-pilot。源码不会读取个人牌组或向外部模型服务发送局面。'])
    (LOCAL / 'report.md').write_text('\n'.join(text) + '\n', encoding='utf-8')
    picture = ''
    if 'baseline' in cases:
        image = cases['baseline'][0].parent / 'final-board.png'
        if image.exists(): picture = f'<figure><img src="{image.relative_to(LOCAL).as_posix()}" alt="原生引擎的真实终场"><figcaption>后台原生场地截图。练习界面显示预设对手手牌；模型输入已另外遮蔽未知身份。</figcaption></figure>'
    page = '''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>ygo-agent 本机指导试验</title><style>
:root{color-scheme:light;font:16px/1.65 system-ui,"Microsoft YaHei",sans-serif;color:#203234;background:#f3f5f1}*{box-sizing:border-box}body{margin:0}main{max-width:1080px;margin:auto;padding:48px 24px}h1{font-size:36px;line-height:1.3;letter-spacing:-1px;margin:12px 0}h2{font-size:22px;margin:10px 0}p{max-width:850px}.eyebrow{font-size:12px;letter-spacing:1.5px;color:#50706c;font-weight:650}.metrics{display:flex;gap:16px;flex-wrap:wrap;margin:30px 0}.metric{flex:1;min-width:160px;background:#164e46;color:white;padding:20px 24px;border-radius:12px}.metric strong{font-size:30px;display:block}.metric span{opacity:.8;font-size:13px}section{background:white;padding:24px;margin:20px 0;border:1px solid #d8e0d9;border-radius:12px}.board{font-weight:600;color:#245d50}summary{cursor:pointer;padding:10px 0;color:#285f53}ol{padding-left:28px}li{padding:6px 10px}small{display:block;color:#687977}a{color:#275e54}figure{margin:28px 0}img{display:block;max-width:100%;border-radius:12px}figcaption{font-size:12px;color:#667773;margin-top:8px}.note{border-left:4px solid #b28a37;padding:8px 20px;background:#faf5e9;border-radius:4px}footer{font-size:13px;color:#687977;margin-top:30px}@media(max-width:600px){main{padding:28px 16px}h1{font-size:28px}section{padding:18px}}
</style><main><div class="eyebrow">LOCAL EXPERIMENT · CPU</div><h1>真实引擎中的逐步指导试验</h1>
<p>使用现成 ygo-agent 策略，在工具箱的真实规则引擎内进行相剑练习。下一步建议来自模型，没有使用预录展开路线。</p>'''
    page += f'<div class="metrics"><div class="metric"><strong>{len(cases)}</strong><span>指定起手案例</span></div><div class="metric"><strong>{accepted}</strong><span>引擎确认的实际选择</span></div><div class="metric"><strong>{timing} ms</strong><span>特征适配与推理中位耗时</span></div></div>'
    page += '<p class="note">这是可行性试验，未训练模型，未进行胜率测试，尚未接入正式助手界面。模型速度不包含首次加载、动画与规则结算。</p>'
    page += ''.join(blocks) + picture
    page += '<section><h2>仍需补齐</h2><ul>' + ''.join('<li>' + html.escape(x) + '</li>' for x in LIMITS) + '</ul></section>'
    page += f'<footer>报告生成：{date.today()} · 权重：0546_26550M.tflite · Windows x64 · CPU 两线程 · 资产 SHA-256 固定校验<br>全部记录保存在本机，实验不调用云端推理服务。</footer></main></html>'
    (LOCAL / 'report.html').write_text(page, encoding='utf-8')
    print(json.dumps(metrics, ensure_ascii=False))
    print(LOCAL / 'report.html')


if __name__ == '__main__': main()
