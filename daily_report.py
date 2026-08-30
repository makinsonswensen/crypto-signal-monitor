# -*- coding: utf-8 -*-
"""
动量筛选日报生成器
汇总当天所有4h扫描结果，生成飞书日报卡片
"""
import json
import glob
import os
from datetime import datetime

import notifier
import config


def collect_today_results():
    """收集当天所有扫描结果"""
    today_str = datetime.now().strftime('%Y%m%d')
    pattern = f"screener_4h_{today_str}_*.json"
    files = sorted(glob.glob(pattern))

    results = []
    for f in files:
        try:
            with open(f, 'r', encoding='utf-8') as fp:
                data = json.load(fp)
                data['_file'] = f
                results.append(data)
        except Exception:
            continue
    return results


def generate_daily_report(results):
    """生成日报内容"""
    if not results:
        return "今日暂无扫描数据。", 'blue'

    # 取最新一次扫描作为当前状态
    latest = results[-1]
    latest_time = datetime.fromisoformat(latest['run_time']).strftime('%Y-%m-%d %H:%M')

    # 统计全天数据
    scan_count = len(results)
    vol_expansion = latest['single_condition_hits'].get('volume_expansion', [])
    mtm_up = latest['single_condition_hits'].get('mtm_cross_up', [])
    mtm_down = latest['single_condition_hits'].get('mtm_cross_down', [])
    pre_selected = latest.get('pre_selected', [])
    selected = latest.get('selected', [])

    # 全天MTM上穿/下穿事件汇总（去重）
    all_up_symbols = set()
    all_down_symbols = set()
    for r in results:
        for item in r['single_condition_hits'].get('mtm_cross_up', []):
            all_up_symbols.add(item['symbol'])
        for item in r['single_condition_hits'].get('mtm_cross_down', []):
            all_down_symbols.add(item['symbol'])

    # 量能放大TOP10
    vol_top10 = sorted(vol_expansion, key=lambda x: x['volume_ratio'], reverse=True)[:10]

    # 预选TOP10（量比最高的）
    pre_top10 = sorted(pre_selected, key=lambda x: x['volume_ratio'], reverse=True)[:10]

    # 市场温度：站上EMA20的比例（从预选推算：预选=量能+EMA，量能放大有X个，预选有Y个，说明大部分量能放大的都站上了EMA）
    # 由于JSON没存price_above_ema总数，用预选/量能放大比例估算
    if vol_expansion:
        ema_ratio = len(pre_selected) / len(vol_expansion) * 100
    else:
        ema_ratio = 0

    # 判断市场状态
    if selected:
        template = 'green'
        title = f"📈 动量筛选日报 - {datetime.now().strftime('%Y-%m-%d')} - 有入选信号"
    elif mtm_up or pre_selected:
        template = 'orange'
        title = f"📊 动量筛选日报 - {datetime.now().strftime('%Y-%m-%d')} - 量能活跃"
    else:
        template = 'blue'
        title = f"📋 动量筛选日报 - {datetime.now().strftime('%Y-%m-%d')} - 市场平静"

    lines = [
        f"**报告日期**: {datetime.now().strftime('%Y-%m-%d')}",
        f"**数据截止**: {latest_time}",
        f"**扫描次数**: 今日共 {scan_count} 次4h周期扫描",
        "",
        f"**📊 市场概览**:",
        f"  量能放大币种: {len(vol_expansion)} 个（量比>=1.2）",
        f"  MTM零轴上穿: {len(mtm_up)} 个（动量转强）",
        f"  MTM零轴下穿: {len(mtm_down)} 个（动量转弱）",
        f"  2/3预选观察: {len(pre_selected)} 个",
        f"  最终入选: {len(selected)} 个",
        f"  市场温度: {ema_ratio:.0f}% 量能放大币种处于上升趋势",
        "",
    ]

    # 量能放大TOP10
    if vol_top10:
        lines.append("**🔥 量能放大TOP10（最新）**:")
        for i, item in enumerate(vol_top10, 1):
            sym = item['symbol'].replace('/USDT:USDT', '').replace('/USDT', '')
            lines.append(f"  {i}. {sym:<10} 价格: {item['price']:<10.4f} 量比: {item['volume_ratio']:.2f}x")
        lines.append("")

    # MTM上穿汇总
    if all_up_symbols:
        lines.append(f"**🟢 MTM零轴上穿（今日共{len(all_up_symbols)}个）**:")
        lines.append(f"  {', '.join(sorted(all_up_symbols))}")
        lines.append("")

    # MTM下穿汇总
    if all_down_symbols:
        lines.append(f"**🔴 MTM零轴下穿（今日共{len(all_down_symbols)}个）**:")
        lines.append(f"  {', '.join(sorted(all_down_symbols))}")
        lines.append("")

    # 预选观察TOP10
    if pre_top10:
        lines.append(f"**👀 2/3预选观察TOP10（最新，按量比排序）**:")
        for i, item in enumerate(pre_top10, 1):
            sym = item['symbol'].replace('/USDT:USDT', '').replace('/USDT', '')
            lines.append(f"  {i}. {sym:<10} 价格: {item['price']:<10.4f} 量比: {item['volume_ratio']:.2f}x  已满足: {item['met_conditions']}")
        lines.append("")

    # 最终入选
    if selected:
        lines.append(f"**✅ 最终入选（三条件全满足，共{len(selected)}个）**:")
        for i, item in enumerate(selected, 1):
            sym = item['symbol'].replace('/USDT:USDT', '').replace('/USDT', '')
            lines.append(f"  {i}. {sym:<10} 价格: {item['price']:<10.4f} 量比: {item['volume_ratio']:.2f}x")
        lines.append("")

    # 总结点评
    lines.append("**📝 今日点评**:")
    if len(vol_expansion) >= 30:
        lines.append("  市场量能全面放大，处于高活跃度状态。")
        lines.append("  大量币种放量上涨，注意区分是趋势延续还是顶部放量。")
    elif len(vol_expansion) >= 10:
        lines.append("  市场活跃度中等，部分币种有资金流入迹象。")
        lines.append("  重点关注预选名单中量比最高的几个，等待MTM确认。")
    else:
        lines.append("  市场整体量能偏低，处于观望期。")
        lines.append("  建议耐心等待动量转折信号出现。")

    if not mtm_up and pre_selected:
        lines.append("  今日无MTM零轴上穿，但有多个币种放量+站上EMA。")
        lines.append("  这些币处于蓄势阶段，一旦MTM上穿零轴就是确认信号。")

    content = '\n'.join(lines)
    return title, content, template


def main():
    print("=" * 60)
    print(f"  动量筛选日报生成器")
    print(f"  日期: {datetime.now().strftime('%Y-%m-%d')}")
    print("=" * 60)

    results = collect_today_results()
    print(f"\n找到 {len(results)} 份今日扫描结果")

    if not results:
        print("今日无扫描数据，日报生成失败。")
        return

    title, content, template = generate_daily_report(results)

    print(f"\n{'='*60}")
    print(f"  日报内容预览")
    print(f"{'='*60}")
    print(content)
    print(f"{'='*60}")

    # 推送到飞书（用筛选系统的独立Webhook）
    print("\n[飞书] 正在推送日报...")
    webhook_url = config.SCREENER_FEISHU_WEBHOOK_URL or None
    success = notifier.send_feishu_message(title, content, is_markdown=True, template=template, webhook_url=webhook_url)

    if success:
        print("[完成] 日报已推送到飞书")
    else:
        print("[失败] 飞书推送失败")


if __name__ == "__main__":
    main()
