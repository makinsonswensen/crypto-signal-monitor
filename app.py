# -*- coding: utf-8 -*-
"""
网页仪表盘
Flask Web应用，实时展示交易信号监控状态
支持多周期展示
"""
from flask import Flask, render_template, jsonify, request
from datetime import datetime

import config
from signal_monitor import get_monitor

app = Flask(__name__)
app.config['JSON_AS_ASCII'] = False


@app.route('/')
def index():
    """仪表盘主页"""
    monitor = get_monitor()
    status = monitor.get_status()
    # 构建周期标签映射
    timeframe_labels = {
        tf: cfg.get('label', tf)
        for tf, cfg in config.TIMEFRAME_CONFIGS.items()
        if cfg.get('enabled', False)
    }
    return render_template('index.html',
                           status=status,
                           watchlist=config.WATCHLIST,
                           timeframes=config.ENABLED_TIMEFRAMES,
                           timeframe_labels=timeframe_labels,
                           patterns=config.ENABLED_PATTERNS)


@app.route('/api/status')
def api_status():
    """获取监控状态API"""
    monitor = get_monitor()
    return jsonify(monitor.get_status())


@app.route('/api/signals')
def api_signals():
    """获取最近信号API（支持按周期筛选）"""
    monitor = get_monitor()
    limit = request.args.get('limit', 50, type=int)
    timeframe = request.args.get('timeframe', None)  # 可选参数
    signals = monitor.get_recent_signals(limit, timeframe=timeframe)
    return jsonify({
        'signals': signals,
        'total': len(signals),
        'timeframe': timeframe,
    })


@app.route('/api/scan', methods=['POST'])
def api_scan():
    """手动触发扫描（支持指定周期）"""
    monitor = get_monitor()
    timeframe = request.json.get('timeframe') if request.is_json else None
    if not timeframe:
        timeframe = request.args.get('timeframe')

    if timeframe:
        result = monitor.scan_all(timeframe)
    else:
        # 扫描所有周期
        result = {}
        for tf in config.ENABLED_TIMEFRAMES:
            result[tf] = monitor.scan_all(tf)
    return jsonify(result)


@app.route('/api/symbol/<symbol>')
def api_symbol_signals(symbol):
    """获取指定交易对的信号历史"""
    monitor = get_monitor()
    signals = monitor.get_signals_by_symbol(symbol)
    return jsonify({
        'symbol': symbol,
        'signals': signals,
        'total': len(signals),
    })


def run_web_app():
    """启动Web应用"""
    print(f"[Web仪表盘] 启动中...")
    print(f"[Web仪表盘] 访问地址: http://{config.WEB_HOST}:{config.WEB_PORT}")
    app.run(host=config.WEB_HOST, port=config.WEB_PORT, debug=False)


if __name__ == '__main__':
    run_web_app()
