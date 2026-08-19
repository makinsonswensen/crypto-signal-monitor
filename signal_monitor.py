# -*- coding: utf-8 -*-
"""
信号监控引擎
负责定时扫描、信号检测、去重、通知调度
支持多周期独立监控
"""
import json
import os
from datetime import datetime
from collections import defaultdict

import config
from data_fetcher import get_data_fetcher
from pattern_detector import scan_patterns
from notifier import send_signal_notification, send_daily_summary, send_hourly_report, send_pre_scan_reminder


class SignalMonitor:
    """信号监控器 - 支持多周期"""

    def __init__(self):
        self.fetcher = get_data_fetcher()
        self.signal_history = []
        self.last_scan_time = None
        self.scan_count = 0
        self.total_signals_found = 0

        # 每个周期的独立状态
        self.timeframe_status = {}
        for tf in config.ENABLED_TIMEFRAMES:
            self.timeframe_status[tf] = {
                'scan_count': 0,
                'last_scan_time': None,
                'signals_found': 0,
            }

        # 加载历史信号
        self._load_history()

        # 去重用的字典：key = "timeframe_symbol_pattern"，value = 最后提醒时间
        # 每个周期独立去重
        self._last_alert_time = {}

    def _load_history(self):
        """加载历史信号记录"""
        try:
            if os.path.exists(config.SIGNAL_HISTORY_FILE):
                with open(config.SIGNAL_HISTORY_FILE, 'r', encoding='utf-8') as f:
                    self.signal_history = json.load(f)
                print(f"[历史记录] 已加载 {len(self.signal_history)} 条历史信号")
        except Exception as e:
            print(f"[历史记录加载失败] {e}")
            self.signal_history = []

    def _save_history(self):
        """保存历史信号记录"""
        try:
            # 只保留最新的N条
            if len(self.signal_history) > config.MAX_HISTORY_SIGNALS:
                self.signal_history = self.signal_history[-config.MAX_HISTORY_SIGNALS:]

            with open(config.SIGNAL_HISTORY_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.signal_history, f, ensure_ascii=False, indent=2, default=str)
        except Exception as e:
            print(f"[历史记录保存失败] {e}")

    def _get_dedup_window(self, timeframe):
        """获取指定周期的去重时间窗口（分钟）"""
        tf_config = config.TIMEFRAME_CONFIGS.get(timeframe, {})
        return tf_config.get('deduplication_minutes', 240)

    def _should_alert(self, timeframe, symbol, pattern):
        """
        判断是否应该发送提醒（去重逻辑）

        同一交易对的同一形态，在去重时间窗口内只提醒一次
        每个周期独立去重
        """
        key = f"{timeframe}_{symbol}_{pattern}"
        now = datetime.now()
        window = self._get_dedup_window(timeframe)

        if key in self._last_alert_time:
            last_time = self._last_alert_time[key]
            if isinstance(last_time, str):
                last_time = datetime.fromisoformat(last_time)
            elapsed = (now - last_time).total_seconds() / 60
            if elapsed < window:
                return False

        self._last_alert_time[key] = now
        return True

    def scan_symbol(self, symbol, timeframe):
        """
        扫描单个交易对指定周期的形态信号

        Args:
            symbol: 交易对名称
            timeframe: K线周期

        Returns:
            list: 检测到的新信号列表（已去重）
        """
        df = self.fetcher.fetch_ohlcv(symbol, timeframe, config.KLIMIT)
        if df is None or len(df) < 3:
            return []

        all_signals = scan_patterns(df)
        if not all_signals:
            return []

        # 过滤掉已经提醒过的信号
        new_signals = []
        for signal in all_signals:
            if self._should_alert(timeframe, symbol, signal['pattern']):
                signal['symbol'] = symbol
                signal['timeframe'] = timeframe
                signal['timeframe_label'] = config.TIMEFRAME_CONFIGS.get(timeframe, {}).get('label', timeframe)
                signal['detected_at'] = datetime.now().isoformat()
                new_signals.append(signal)

        # 记录到历史
        for signal in new_signals:
            self.signal_history.append(signal)
            self.total_signals_found += 1
        # 更新周期统计
        if timeframe in self.timeframe_status:
            self.timeframe_status[timeframe]['signals_found'] += len(new_signals)

        if new_signals:
            self._save_history()

        return new_signals

    def scan_all(self, timeframe=None):
        """
        扫描所有监控的交易对

        Args:
            timeframe: 指定扫描的周期，为None则扫描所有启用的周期

        Returns:
            dict: 扫描结果
        """
        if timeframe is None:
            # 扫描所有周期
            all_results = {}
            for tf in config.ENABLED_TIMEFRAMES:
                result = self.scan_all(tf)
                all_results[tf] = result
            return all_results

        tf_config = config.TIMEFRAME_CONFIGS.get(timeframe, {})
        tf_label = tf_config.get('label', timeframe)

        print(f"\n{'='*60}")
        print(f"[开始扫描] [{tf_label}周期] {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"[监控交易对] {len(config.WATCHLIST)} 个")
        print(f"{'='*60}")

        self.last_scan_time = datetime.now()
        self.scan_count += 1

        # 更新周期统计
        if timeframe in self.timeframe_status:
            self.timeframe_status[timeframe]['scan_count'] += 1
            self.timeframe_status[timeframe]['last_scan_time'] = datetime.now().isoformat()

        symbols_with_signals = []

        for i, symbol in enumerate(config.WATCHLIST):
            print(f"[{i+1}/{len(config.WATCHLIST)}] 扫描 {symbol}...", end=' ')

            signals = self.scan_symbol(symbol, timeframe)

            if signals:
                print(f"发现 {len(signals)} 个信号!")
                symbols_with_signals.append({
                    'symbol': symbol,
                    'signals': signals
                })
                # 发送通知
                send_signal_notification(signals, symbol, timeframe)
            else:
                print("无信号")

        # 扫描结束汇总
        print(f"\n{'='*60}")
        print(f"[{tf_label}周期 扫描完成] 共发现 {len(symbols_with_signals)} 个交易对有信号")
        print(f"[累计信号] {self.timeframe_status.get(timeframe, {}).get('signals_found', 0)} 个")
        print(f"{'='*60}\n")

        # 发送汇总报告
        if symbols_with_signals:
            if timeframe == '1h':
                send_hourly_report(symbols_with_signals, len(config.WATCHLIST))
            elif timeframe == '4h':
                send_daily_summary(symbols_with_signals, len(config.WATCHLIST))

        return {
            'timeframe': timeframe,
            'timeframe_label': tf_label,
            'scan_time': datetime.now().isoformat(),
            'total_scanned': len(config.WATCHLIST),
            'symbols_with_signals': symbols_with_signals,
            'total_signals': sum(len(s['signals']) for s in symbols_with_signals),
        }

    def get_status(self):
        """获取监控器状态"""
        return {
            'scan_count': self.scan_count,
            'last_scan_time': self.last_scan_time.isoformat() if self.last_scan_time else None,
            'total_signals_found': self.total_signals_found,
            'watchlist_size': len(config.WATCHLIST),
            'enabled_timeframes': config.ENABLED_TIMEFRAMES,
            'timeframe_configs': {
                tf: {
                    'label': cfg.get('label', tf),
                    'scan_count': self.timeframe_status.get(tf, {}).get('scan_count', 0),
                    'last_scan_time': self.timeframe_status.get(tf, {}).get('last_scan_time'),
                    'signals_found': self.timeframe_status.get(tf, {}).get('signals_found', 0),
                }
                for tf, cfg in config.TIMEFRAME_CONFIGS.items()
                if cfg.get('enabled', False)
            },
            'enabled_patterns': config.ENABLED_PATTERNS,
            'history_count': len(self.signal_history),
        }

    def get_recent_signals(self, limit=50, timeframe=None):
        """获取最近的信号"""
        signals = self.signal_history
        if timeframe:
            signals = [s for s in signals if s.get('timeframe') == timeframe]
        # 返回最近的N条，按时间倒序
        recent = signals[-limit:][::-1]
        return recent

    def get_signals_by_symbol(self, symbol):
        """获取指定交易对的历史信号"""
        return [s for s in self.signal_history if s.get('symbol') == symbol][::-1]


# 全局单例
_monitor = None


def get_monitor():
    global _monitor
    if _monitor is None:
        _monitor = SignalMonitor()
    return _monitor


if __name__ == '__main__':
    monitor = SignalMonitor()
    result = monitor.scan_all('1h')
    print(f"\n1小时周期扫描结果:")
    print(f"  扫描交易对: {result['total_scanned']}")
    print(f"  有信号的交易对: {len(result['symbols_with_signals'])}")
    print(f"  总信号数: {result['total_signals']}")
