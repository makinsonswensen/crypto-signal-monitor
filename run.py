# -*- coding: utf-8 -*-
"""
交易信号监控系统 - 主启动脚本
支持多周期监控（1小时 + 4小时）
整合定时任务、Web仪表盘、多通道通知
"""
import os
import sys
import time
import threading
from datetime import datetime

# 添加当前目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config
from signal_monitor import get_monitor
try:
    from ma_monitor import get_ma_monitor
except ImportError:
    # MA 共振模块已迁移至 trading-cockpit/monitor/，
    # 本仓库默认 ENABLE_MA_RESONANCE=False，缺失模块不影响 K 线形态扫描
    get_ma_monitor = None
from notifier import send_pre_scan_reminder


def setup_scheduler():
    """设置定时任务调度器 - 支持多周期"""
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.cron import CronTrigger

    scheduler = BackgroundScheduler(timezone='Asia/Shanghai')
    monitor = get_monitor()

    print(f"[定时任务] 启用周期: {config.ENABLED_TIMEFRAMES}")

    for timeframe in config.ENABLED_TIMEFRAMES:
        tf_config = config.TIMEFRAME_CONFIGS.get(timeframe, {})
        tf_label = tf_config.get('label', timeframe)
        scan_mode = tf_config.get('scan_mode', 'fixed')

        print(f"\n[{tf_label}周期] 扫描模式: {scan_mode}")

        if scan_mode == 'cron':
            # cron模式：每小时的第X分钟扫描（适用于1小时周期）
            cron_minute = tf_config.get('cron_minute', 55)

            # 创建扫描任务函数（绑定当前timeframe）
            def make_scan_job(tf):
                def scan_job():
                    monitor.scan_all(tf)
                return scan_job

            scheduler.add_job(
                make_scan_job(timeframe),
                CronTrigger(minute=cron_minute),
                id=f'scan_{timeframe}',
                name=f'{tf_label}周期扫描',
                misfire_grace_time=600
            )
            print(f"  - 扫描任务: 每小时第 {cron_minute} 分钟")

            # 盘前提醒
            pre_minutes = tf_config.get('pre_reminder_minutes', 0)
            if pre_minutes > 0:
                pre_minute = cron_minute - pre_minutes
                if pre_minute < 0:
                    pre_minute += 60
                # 这里简化处理：每小时提前pre_minutes分钟提醒
                def make_pre_job(tf, lbl):
                    def pre_job():
                        send_pre_scan_reminder(tf)
                    return pre_job

                scheduler.add_job(
                    make_pre_job(timeframe, tf_label),
                    CronTrigger(minute=pre_minute),
                    id=f'pre_scan_{timeframe}',
                    name=f'{tf_label}盘前提醒',
                    misfire_grace_time=300
                )
                print(f"  - 盘前提醒: 每小时第 {pre_minute} 分钟")

        elif scan_mode == 'fixed':
            # 固定时间模式：每天指定时间点扫描（适用于4小时周期）
            fixed_times = tf_config.get('fixed_times', [])
            pre_minutes = tf_config.get('pre_reminder_minutes', 0)

            for scan_time in fixed_times:
                hour, minute = map(int, scan_time.split(':'))

                # 盘前预备提醒
                if pre_minutes > 0:
                    pre_total_minutes = hour * 60 + minute - pre_minutes
                    pre_hour = pre_total_minutes // 60
                    pre_min = pre_total_minutes % 60
                    if pre_hour < 0:
                        pre_hour += 24

                    def make_pre_job(tf, lbl):
                        def pre_job():
                            send_pre_scan_reminder(tf)
                        return pre_job

                    scheduler.add_job(
                        make_pre_job(timeframe, tf_label),
                        CronTrigger(hour=pre_hour, minute=pre_min),
                        id=f'pre_scan_{timeframe}_{scan_time}',
                        name=f'{tf_label}盘前提醒-{scan_time}',
                        misfire_grace_time=300
                    )
                    print(f"  - 盘前提醒: {pre_hour:02d}:{pre_min:02d}")

                # 正式扫描任务
                def make_scan_job(tf):
                    def scan_job():
                        monitor.scan_all(tf)
                    return scan_job

                scheduler.add_job(
                    make_scan_job(timeframe),
                    CronTrigger(hour=hour, minute=minute),
                    id=f'scan_{timeframe}_{scan_time}',
                    name=f'{tf_label}扫描-{scan_time}',
                    misfire_grace_time=600
                )
                print(f"  - 扫描任务: {scan_time}")

    # MA 多周期均线共振扫描（每根 5m K线收盘后执行）
    if config.ENABLE_MA_RESONANCE:
        if get_ma_monitor is None:
            print("[警告] ENABLE_MA_RESONANCE=True 但 ma_monitor 模块缺失，跳过 MA 共振。"
                  "该功能已迁移至 trading-cockpit/monitor/")
        else:
            ma_monitor = get_ma_monitor()
            scheduler.add_job(
                ma_monitor.scan_all,
                CronTrigger(minute='*/5', second=config.MA_SCAN_SECOND),
                id='ma_resonance_scan',
                name='MA均线共振扫描',
                misfire_grace_time=120
            )
            print(f"\n[MA共振周期] {' + '.join(config.MA_RESONANCE_TIMEFRAMES)}")
            print(f"  - 扫描任务: 每 5 分钟的第 {config.MA_SCAN_SECOND} 秒"
                  f"（对应 {'/'.join(config.MA_RESONANCE_TIMEFRAMES)} K线收盘后）")

    return scheduler


def print_banner():
    """打印启动横幅"""
    banner = """
╔══════════════════════════════════════════════════════════╗
║           交易信号监控系统 v2.0                           ║
║           Crypto Signal Monitor (Multi-Timeframe)        ║
╠══════════════════════════════════════════════════════════╣
║  基于K线形态识别的多周期自动信号监控与提醒系统              ║
╚══════════════════════════════════════════════════════════╝
"""
    print(banner)
    print(f"[启动时间] {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    exchange_names = [ex.get('name', ex.get('id')) for ex in config.EXCHANGE_LIST]
    print(f"[数据源] {', '.join(exchange_names)} (共{len(config.EXCHANGE_LIST)}个，自动降级)")
    print(f"[监控交易对] {len(config.WATCHLIST)} 个")
    print(f"[启用周期] {len(config.ENABLED_TIMEFRAMES)} 个: {', '.join(config.ENABLED_TIMEFRAMES)}")
    print(f"[监控形态] {len(config.ENABLED_PATTERNS)} 种")
    if config.ENABLE_MA_RESONANCE:
        print(f"[MA均线共振] 启用 | 周期 {' + '.join(config.MA_RESONANCE_TIMEFRAMES)}"
              f" | 均线 {'/'.join(str(p) for p in config.MA_PERIODS)}")
    else:
        print("[MA均线共振] 禁用")
    print(f"[飞书推送] {'启用' if config.ENABLE_FEISHU else '禁用'}")
    print(f"[桌面弹窗] {'启用' if config.ENABLE_DESKTOP_NOTIFY else '禁用'}")
    print(f"[Web仪表盘] {'启用' if config.ENABLE_WEB_DASHBOARD else '禁用'}")
    print()


def main():
    """主函数"""
    print_banner()

    # 初始化监控器
    monitor = get_monitor()
    print("[初始化] 连接交易所...")
    if not monitor.fetcher.test_connection():
        print("[错误] 无法连接交易所，请检查网络和配置")
        return

    print("[初始化] 交易所连接成功")
    print()

    # 启动时执行所有周期的首次扫描
    print("[启动] 执行首次扫描...")
    for timeframe in config.ENABLED_TIMEFRAMES:
        tf_label = config.TIMEFRAME_CONFIGS.get(timeframe, {}).get('label', timeframe)
        print(f"\n--- {tf_label}周期 ---")
        try:
            monitor.scan_all(timeframe)
        except Exception as e:
            print(f"[{tf_label}首次扫描异常] {e}")

    # MA 共振首次判定（状态文件为空时会报告当前已成立的共振）
    if config.ENABLE_MA_RESONANCE and get_ma_monitor is not None:
        print("\n--- MA均线共振 ---")
        try:
            get_ma_monitor().scan_all()
        except Exception as e:
            print(f"[MA共振首次扫描异常] {e}")

    # 设置定时任务
    scheduler = setup_scheduler()
    scheduler.start()
    print(f"\n[定时任务] 调度器已启动")

    # 启动Web仪表盘
    if config.ENABLE_WEB_DASHBOARD:
        from app import app

        def run_web():
            app.run(host=config.WEB_HOST, port=config.WEB_PORT, debug=False, use_reloader=False)

        web_thread = threading.Thread(target=run_web, daemon=True)
        web_thread.start()
        print(f"[Web仪表盘] 已启动: http://{config.WEB_HOST}:{config.WEB_PORT}")

    # 主循环
    print(f"\n{'='*60}")
    print("系统运行中，按 Ctrl+C 停止")
    print(f"{'='*60}\n")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n\n[停止] 正在关闭系统...")
        scheduler.shutdown()
        print("[停止] 系统已安全关闭")


if __name__ == '__main__':
    main()
