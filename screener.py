# -*- coding: utf-8 -*-
"""
动量爆发筛选系统
自动获取币安永续合约交易量前100的交易对，下载K线数据，运行动量+背离逻辑，输出最终入选列表

筛选条件（三重过滤）：
1. 交易量过滤：当前量 > 20周期均量 x 1.2
2. MTM动量突破：MTM从<=0上穿到>0（动量由负转正）
3. 价格均线确认：收盘价站上20周期EMA

改进：
- 同时检测MTM上穿（动量转强）和下穿（动量转弱）
- 2/3预选报告：满足2个条件的币种作为早期观察名单
- 定时自动运行：接入APScheduler，自动扫描+推送飞书

用法：
    python screener.py                    # 默认4h周期，前100
    python screener.py --interval 1h     # 1小时周期
    python screener.py --top 50          # 交易量前50
    python screener.py --save            # 保存结果到JSON文件
    python screener.py --feishu          # 推送结果到飞书
    python screener.py --schedule        # 定时自动运行（4h周期每4小时一次，自动推飞书）
    python screener.py --schedule --interval 1h  # 1h周期定时运行
"""

import ccxt
import pandas as pd
import time
import argparse
import json
from datetime import datetime

import notifier
import config


# ==================== 系统核心配置 ====================
CANDLE_INTERVAL = '4h'            # K线周期：4h / 1h / 1d
LOOKBACK_PERIOD = 12              # MTM指标周期
TOP_N_VOLUME = 100               # 交易量前N
VOLUME_MA_PERIOD = 20            # 成交量均线周期
VOLUME_RATIO_THRESHOLD = 1.1     # 量比阈值（当前量/均量 >= 1.1）
EMA_PERIOD = 20                  # EMA周期
KLIMIT = 100                     # K线获取数量


class MomentumScreener:
    """动量爆发筛选系统"""

    def __init__(self, interval=CANDLE_INTERVAL, lookback=LOOKBACK_PERIOD,
                 top_n=TOP_N_VOLUME):
        self.interval = interval
        self.lookback = lookback
        self.top_n = top_n

        # 日线周期：用前一根已完成K线判断（当天08:01刚开盘，最新K线不完整）
        # 4h/1h周期：用当前K线判断（在K线收盘前2分钟扫描，数据基本完整）
        self.bar_offset = 1 if interval == '1d' else 0

        # 主数据源：币安永续合约
        self.exchange = ccxt.binanceusdm({
            'enableRateLimit': True,
            'timeout': 15000,
            'options': {'defaultType': 'future'},
        })
        # 备用数据源：Gate.io永续合约
        self.exchange_gate = ccxt.gate({
            'enableRateLimit': True,
            'timeout': 15000,
            'options': {'defaultType': 'swap'},
        })
        self.using_gate = False
        offset_info = "（使用前一已完成K线）" if self.bar_offset > 0 else ""
        print(f"[系统] 已连接币安U本位永续合约 | K线周期: {interval}{offset_info} | 筛选范围: 前{top_n}")

    def get_top_contracts(self):
        """步骤1: 获取24h交易量前N的USDT永续合约交易对（币安优先，Gate.io兜底）"""
        print(f"\n[步骤1] 正在获取永续合约交易量排名...")

        # 先尝试币安
        try:
            tickers = self.exchange.fetch_tickers()
            usdt_tickers = {
                symbol: ticker for symbol, ticker in tickers.items()
                if symbol.endswith('/USDT:USDT') or symbol.endswith('/USDT')
            }
            sorted_items = sorted(
                usdt_tickers.items(),
                key=lambda x: x[1].get('quoteVolume', 0) or 0,
                reverse=True
            )
            top_symbols = [item[0] for item in sorted_items[:self.top_n]]
            print(f"  [币安] 共 {len(usdt_tickers)} 个USDT永续合约，已选取交易量前 {len(top_symbols)} 个")
            print(f"  前10名：")
            for i, (symbol, ticker) in enumerate(sorted_items[:10], 1):
                vol = ticker.get('quoteVolume', 0) or 0
                print(f"    {i:>2}. {symbol:<20} 24h量: {vol/1e9:.2f}B USDT")
            return top_symbols
        except Exception as e:
            print(f"  [币安] 获取失败: {e}")

        # 币安失败，切换到Gate.io
        print(f"  [Gate.io] 正在切换到备用数据源...")
        try:
            tickers = self.exchange_gate.fetch_tickers()
            usdt_tickers = {
                symbol: ticker for symbol, ticker in tickers.items()
                if symbol.endswith('/USDT:USDT') or symbol.endswith('/USDT')
            }
            sorted_items = sorted(
                usdt_tickers.items(),
                key=lambda x: x[1].get('quoteVolume', 0) or 0,
                reverse=True
            )
            top_symbols = [item[0] for item in sorted_items[:self.top_n]]
            self.using_gate = True
            print(f"  [Gate.io] 共 {len(usdt_tickers)} 个USDT永续合约，已选取交易量前 {len(top_symbols)} 个")
            print(f"  前10名：")
            for i, (symbol, ticker) in enumerate(sorted_items[:10], 1):
                vol = ticker.get('quoteVolume', 0) or 0
                print(f"    {i:>2}. {symbol:<20} 24h量: {vol/1e9:.2f}B USDT")
            return top_symbols
        except Exception as e:
            print(f"  [Gate.io] 获取也失败: {e}")
            return []

    def fetch_klines(self, symbol):
        """步骤2: 下载单个交易对的K线数据（币安优先，Gate.io兜底）"""
        # 如果合约列表来自Gate.io，直接用Gate.io
        exchanges = [self.exchange_gate] if self.using_gate else [self.exchange, self.exchange_gate]
        for ex in exchanges:
            try:
                ohlcv = ex.fetch_ohlcv(symbol, timeframe=self.interval, limit=KLIMIT)
                if not ohlcv:
                    continue
                df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
                for col in ['open', 'high', 'low', 'close', 'volume']:
                    df[col] = pd.to_numeric(df[col], errors='coerce')
                df.dropna(inplace=True)
                return df
            except Exception:
                continue
        return None

    def screen_symbol(self, df):
        """
        步骤3: 对单个交易对运行动量筛选逻辑

        三重过滤：
        1. 交易量过滤 - 当前量 > 20周期均量 * 1.1
        2. MTM动量突破 - MTM从<=0上穿到>0（上穿）或从>0下穿到<=0（下穿）
        3. 价格均线确认 - 收盘价站上20EMA

        Returns:
            (result, stats) - result为入选详情或None，stats为各条件命中情况
        """
        min_len = max(50, self.lookback + 5, VOLUME_MA_PERIOD + 5)
        if len(df) < min_len:
            return None, None

        # bar_offset: 日线周期=1（用前一根已完成K线），4h/1h=0（用当前K线）
        off = self.bar_offset
        idx_now = -1 - off      # 当前判断K线的位置
        idx_prev = -2 - off     # 前一根K线的位置

        # 1. 交易量过滤
        vol_ma = df['volume'].rolling(VOLUME_MA_PERIOD).mean()
        vol_ma_last = vol_ma.iloc[idx_now]
        if pd.isna(vol_ma_last) or vol_ma_last <= 0:
            return None, None
        vol_ratio = df['volume'].iloc[idx_now] / vol_ma_last
        is_volume_ok = vol_ratio >= VOLUME_RATIO_THRESHOLD

        # 2. MTM动量计算
        mtm = df['close'] - df['close'].shift(self.lookback)
        mtm_now = mtm.iloc[idx_now]
        mtm_prev = mtm.iloc[idx_prev]
        if pd.isna(mtm_now) or pd.isna(mtm_prev):
            return None, None
        is_mtm_cross_up = (mtm_now > 0) and (mtm_prev <= 0)
        is_mtm_cross_down = (mtm_now <= 0) and (mtm_prev > 0)

        # 3. 价格均线确认
        ema = df['close'].ewm(span=EMA_PERIOD, adjust=False).mean()
        is_price_above_ema = df['close'].iloc[idx_now] > ema.iloc[idx_now]
        is_price_below_ema = not is_price_above_ema

        # 条件命中数（0-3）
        conditions_met = sum([is_volume_ok, is_mtm_cross_up, is_price_above_ema])

        details = {
            'price': float(df['close'].iloc[idx_now]),
            'volume_ratio': round(float(vol_ratio), 2),
            'mtm': round(float(mtm_now), 6),
            'mtm_prev': round(float(mtm_prev), 6),
        }
        stats = {
            'volume_ok': is_volume_ok,
            'mtm_cross_up': is_mtm_cross_up,
            'mtm_cross_down': is_mtm_cross_down,
            'price_above_ema': is_price_above_ema,
            'price_below_ema': is_price_below_ema,
            'conditions_met': conditions_met,
            'details': details,
        }

        if is_volume_ok and is_mtm_cross_up and is_price_above_ema:
            return details, stats
        return None, stats

    def run(self):
        """执行完整筛选流程"""
        start_time = time.time()
        print(f"\n{'='*60}")
        print(f"  动量爆发筛选系统")
        print(f"  周期: {self.interval} | MTM周期: {self.lookback} | EMA: {EMA_PERIOD}")
        print(f"  筛选范围: 交易量前 {self.top_n} 的USDT永续合约")
        print(f"  运行时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'='*60}")

        # 步骤1: 获取合约列表
        symbols = self.get_top_contracts()
        if not symbols:
            print("[错误] 无法获取合约列表，程序终止")
            return []

        # 步骤2+3: 逐个下载K线并筛选
        print(f"\n[步骤2-3] 正在下载K线数据并运行动量筛选...")
        selected = []
        pre_selected = []
        processed = 0
        failed = 0
        stat_counts = {'volume_ok': 0, 'mtm_cross_up': 0, 'mtm_cross_down': 0,
                       'price_above_ema': 0, 'price_below_ema': 0}
        stat_symbols = {'volume_ok': [], 'mtm_cross_up': [], 'mtm_cross_down': [],
                        'price_above_ema': [], 'price_below_ema': []}

        for i, symbol in enumerate(symbols, 1):
            try:
                df = self.fetch_klines(symbol)
                if df is None or len(df) < 50:
                    failed += 1
                    continue

                result, stats = self.screen_symbol(df)
                if stats:
                    for key in stat_counts:
                        if stats[key]:
                            stat_counts[key] += 1
                            stat_symbols[key].append({
                                'symbol': symbol,
                                **stats['details'],
                            })

                    # 预选标准：(MTM上穿 OR MTM下穿) AND 量能放大
                    has_mtm_cross = stats['mtm_cross_up'] or stats['mtm_cross_down']
                    if has_mtm_cross and stats['volume_ok']:
                        if stats['mtm_cross_up']:
                            met_names = 'MTM上穿 + 量能'
                        else:
                            met_names = 'MTM下穿 + 量能'
                        pre_selected.append({
                            'symbol': symbol,
                            **stats['details'],
                            'met_conditions': met_names,
                            'direction': '看多' if stats['mtm_cross_up'] else '看空',
                        })

                if result:
                    selected.append({
                        'symbol': symbol,
                        **result,
                    })

                processed += 1

                if i % 10 == 0 or i == len(symbols):
                    pct = i * 100 // len(symbols)
                    print(f"  进度: {i}/{len(symbols)} ({pct}%) | 入选: {len(selected)} | 预选: {len(pre_selected)} | 失败: {failed}")

            except Exception:
                failed += 1
                continue

        elapsed = time.time() - start_time

        # 结果输出
        print(f"\n{'='*60}")
        print(f"  筛选完成")
        print(f"  已处理: {processed} | 下载失败: {failed} | 入选: {len(selected)} | 预选: {len(pre_selected)}")
        print(f"  耗时: {elapsed:.1f}秒")
        print(f"{'='*60}")

        # 单条件统计（帮助判断市场状态）
        print(f"\n  单条件命中统计（共{processed}个有效币种）：")
        print(f"    交易量放大 (量比>={VOLUME_RATIO_THRESHOLD}):  {stat_counts['volume_ok']:>3} 个")
        print(f"    MTM零轴上穿 (动量转强):                      {stat_counts['mtm_cross_up']:>3} 个")
        print(f"    MTM零轴下穿 (动量转弱):                      {stat_counts['mtm_cross_down']:>3} 个")
        print(f"    价格站上EMA{EMA_PERIOD}:                           {stat_counts['price_above_ema']:>3} 个")
        print(f"    价格在EMA{EMA_PERIOD}之下:                        {stat_counts['price_below_ema']:>3} 个")

        # 市场多空判断
        above_pct = stat_counts['price_above_ema'] / processed * 100 if processed > 0 else 0
        below_pct = stat_counts['price_below_ema'] / processed * 100 if processed > 0 else 0
        if above_pct >= 60:
            market_state = '多头主导'
        elif below_pct >= 60:
            market_state = '空头主导'
        elif above_pct >= 50:
            market_state = '偏多震荡'
        elif below_pct >= 50:
            market_state = '偏空震荡'
        else:
            market_state = '多空均衡'
        print(f"\n  --- 市场多空状态 ---")
        print(f"    EMA{EMA_PERIOD}之上: {stat_counts['price_above_ema']} 个 ({above_pct:.1f}%)")
        print(f"    EMA{EMA_PERIOD}之下: {stat_counts['price_below_ema']} 个 ({below_pct:.1f}%)")
        print(f"    市场状态: {market_state}")
        print(f"  （预选标准: MTM零轴上穿或下穿 + 量能放大）")

        # 单条件具体交易对明细
        if stat_symbols['volume_ok']:
            vol_list = sorted(stat_symbols['volume_ok'], key=lambda x: x['volume_ratio'], reverse=True)
            print(f"\n  --- 交易量放大明细 ({len(vol_list)}个) ---")
            for item in vol_list:
                print(f"    {item['symbol']:<22} 价格: {item['price']:.4f}  量比: {item['volume_ratio']:.2f}")

        if stat_symbols['mtm_cross_up']:
            mtm_up_list = sorted(stat_symbols['mtm_cross_up'], key=lambda x: x['mtm'], reverse=True)
            print(f"\n  --- MTM零轴上穿明细 ({len(mtm_up_list)}个, 动量转强) ---")
            for item in mtm_up_list:
                print(f"    {item['symbol']:<22} 价格: {item['price']:.4f}  MTM: {item['mtm_prev']:.6f} -> {item['mtm']:.6f}")

        if stat_symbols['mtm_cross_down']:
            mtm_down_list = sorted(stat_symbols['mtm_cross_down'], key=lambda x: x['mtm'])
            print(f"\n  --- MTM零轴下穿明细 ({len(mtm_down_list)}个, 动量转弱) ---")
            for item in mtm_down_list:
                print(f"    {item['symbol']:<22} 价格: {item['price']:.4f}  MTM: {item['mtm_prev']:.6f} -> {item['mtm']:.6f}")

        # 预选名单
        if pre_selected:
            pre_selected.sort(key=lambda x: x['volume_ratio'], reverse=True)
            print(f"\n  --- 预选观察名单 ({len(pre_selected)}个) ---")
            for item in pre_selected:
                print(f"    {item['symbol']:<22} 价格: {item['price']:.4f}  量比: {item['volume_ratio']:.2f}  方向: {item['direction']}  已满足: {item['met_conditions']}")

        if selected:
            selected.sort(key=lambda x: x['volume_ratio'], reverse=True)

            print(f"\n{'排名':<5} {'交易对':<22} {'当前价格':<14} {'量比':<8} {'MTM值':<14}")
            print('-' * 65)
            for rank, item in enumerate(selected, 1):
                print(f" {rank:<4}  {item['symbol']:<22} {item['price']:<14.4f} {item['volume_ratio']:<8.2f} {item['mtm']:<14.6f}")

            print(f"\n最终入选交易对列表（{len(selected)}个）：")
            print("  " + ", ".join([s['symbol'] for s in selected]))
        else:
            print("\n  暂无币种同时满足三重过滤条件。")

        print(f"\n{'='*60}")

        self.stat_symbols = stat_symbols
        self.stat_counts = stat_counts
        self.pre_selected = pre_selected
        self.market_state = market_state
        self.ema_stats = {
            'above_ema': stat_counts['price_above_ema'],
            'below_ema': stat_counts['price_below_ema'],
            'above_pct': round(above_pct, 1),
            'below_pct': round(below_pct, 1),
            'market_state': market_state,
        }
        self.run_stats = {
            'processed': processed,
            'failed': failed,
            'selected': selected,
            'pre_selected': pre_selected,
            'elapsed': elapsed,
        }
        return selected

    def send_feishu_report(self):
        """将筛选结果推送到飞书"""
        sc = self.stat_counts
        ss = self.stat_symbols
        rs = self.run_stats
        es = self.ema_stats
        now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        has_hits = sc['volume_ok'] > 0 or sc['mtm_cross_up'] > 0 or sc['mtm_cross_down'] > 0 or len(rs['selected']) > 0
        if len(rs['selected']) > 0:
            template = 'green'
        elif '多头' in es['market_state']:
            template = 'orange'
        elif '空头' in es['market_state']:
            template = 'red'
        else:
            template = 'blue'
        title = f"动量爆发筛选报告 [{self.interval}] {now_str}"

        lines = [
            f"**运行时间**: {now_str}",
            f"**K线周期**: {self.interval} | MTM周期: {self.lookback} | EMA: {EMA_PERIOD}",
            f"**筛选范围**: 交易量前 {self.top_n} 的USDT永续合约",
            f"**已处理**: {rs['processed']} | 失败: {rs['failed']} | 耗时: {rs['elapsed']:.1f}秒",
            "",
            f"**市场多空状态**:",
            f"  EMA{EMA_PERIOD}之上: {es['above_ema']} 个 ({es['above_pct']}%)",
            f"  EMA{EMA_PERIOD}之下: {es['below_ema']} 个 ({es['below_pct']}%)",
            f"  市场状态: {es['market_state']}",
            "",
            f"**单条件命中统计**:",
            f"  交易量放大 (量比>={VOLUME_RATIO_THRESHOLD}): {sc['volume_ok']} 个",
            f"  MTM零轴上穿 (动量转强): {sc['mtm_cross_up']} 个",
            f"  MTM零轴下穿 (动量转弱): {sc['mtm_cross_down']} 个",
        ]

        if ss['volume_ok']:
            vol_list = sorted(ss['volume_ok'], key=lambda x: x['volume_ratio'], reverse=True)
            lines.append("")
            lines.append("**交易量放大明细**:")
            for item in vol_list:
                lines.append(f"  {item['symbol']}  价格: {item['price']:.4f}  量比: {item['volume_ratio']:.2f}")

        if ss['mtm_cross_up']:
            symbols_up = [item['symbol'] for item in ss['mtm_cross_up']]
            lines.append("")
            lines.append(f"**MTM零轴上穿 ({len(symbols_up)}个, 动量转强)**:")
            lines.append(f"  {', '.join(symbols_up)}")

        if ss['mtm_cross_down']:
            symbols_down = [item['symbol'] for item in ss['mtm_cross_down']]
            lines.append("")
            lines.append(f"**MTM零轴下穿 ({len(symbols_down)}个, 动量转弱)**:")
            lines.append(f"  {', '.join(symbols_down)}")

        if rs.get('pre_selected'):
            ps_list = sorted(rs['pre_selected'], key=lambda x: x['volume_ratio'], reverse=True)
            lines.append("")
            lines.append(f"**预选观察名单 ({len(ps_list)}个, MTM穿越+量能放大)**:")
            for item in ps_list:
                lines.append(f"  {item['symbol']}  价格: {item['price']:.4f}  量比: {item['volume_ratio']:.2f}  方向: {item['direction']}  {item['met_conditions']}")

        if rs['selected']:
            lines.append("")
            lines.append(f"**最终入选 ({len(rs['selected'])}个, 三条件全部满足)**:")
            for rank, item in enumerate(rs['selected'], 1):
                lines.append(f"  {rank}. {item['symbol']}  价格: {item['price']:.4f}  量比: {item['volume_ratio']:.2f}")
        else:
            lines.append("")
            lines.append("暂无币种同时满足三重过滤条件。")

        content = '\n'.join(lines)
        webhook_url = config.SCREENER_FEISHU_WEBHOOK_URL or None
        notifier.send_feishu_message(title, content, is_markdown=True, template=template, webhook_url=webhook_url)


def run_scheduled_scan(interval, top_n, lookback, save=False):
    """定时扫描任务：执行筛选 + 自动推送飞书 + 可选保存JSON"""
    print(f"\n{'='*60}")
    print(f"[定时任务] 开始自动扫描 | 时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}")

    screener = MomentumScreener(interval=interval, lookback=lookback, top_n=top_n)
    results = screener.run()
    print("\n[定时任务] 正在推送飞书报告...")
    screener.send_feishu_report()

    if save:
        filename = f"screener_{interval}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        save_data = {
            'run_time': datetime.now().isoformat(),
            'interval': interval,
            'lookback': lookback,
            'top_n': top_n,
            'selected_count': len(results),
            'selected': results,
            'pre_selected': screener.pre_selected,
            'ema_stats': screener.ema_stats,
            'single_condition_hits': {
                'volume_expansion': screener.stat_symbols.get('volume_ok', []),
                'mtm_cross_up': screener.stat_symbols.get('mtm_cross_up', []),
                'mtm_cross_down': screener.stat_symbols.get('mtm_cross_down', []),
                'price_above_ema': screener.stat_symbols.get('price_above_ema', []),
                'price_below_ema': screener.stat_symbols.get('price_below_ema', []),
            },
        }
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(save_data, f, ensure_ascii=False, indent=2)
        print(f"[定时任务] 结果已保存到: {filename}")

    print(f"[定时任务] 完成\n")


def setup_scheduler(interval, top_n, lookback, save=False):
    """设置APScheduler定时任务"""
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.cron import CronTrigger

    scheduler = BackgroundScheduler(timezone='Asia/Shanghai')

    if interval == '4h':
        scan_times = ['03:58', '07:58', '11:58', '15:58', '19:58', '23:58']
        for st in scan_times:
            hour, minute = map(int, st.split(':'))
            scheduler.add_job(
                run_scheduled_scan, CronTrigger(hour=hour, minute=minute),
                args=[interval, top_n, lookback, save],
                id=f'screener_{interval}_{st}',
                name=f'筛选扫描-{interval}-{st}',
                misfire_grace_time=600
            )
        print(f"[定时任务] 4h周期: 每天 {', '.join(scan_times)} 自动扫描（提前2分钟扫描K线收盘前数据）")
    elif interval == '1h':
        scheduler.add_job(
            run_scheduled_scan, CronTrigger(minute=5),
            args=[interval, top_n, lookback, save],
            id=f'screener_{interval}',
            name=f'筛选扫描-{interval}',
            misfire_grace_time=600
        )
        print(f"[定时任务] 1h周期: 每小时第5分钟自动扫描")
    elif interval == '1d':
        scheduler.add_job(
            run_scheduled_scan, CronTrigger(hour=8, minute=1),
            args=[interval, top_n, lookback, save],
            id=f'screener_{interval}',
            name=f'筛选扫描-{interval}',
            misfire_grace_time=600
        )
        print(f"[定时任务] 1d周期: 每天 08:01 (北京时间) 自动扫描")

    return scheduler


def main():
    parser = argparse.ArgumentParser(
        description='动量爆发筛选系统 - 自动筛选交易量前100合约中的动量突破币种',
    )
    parser.add_argument('--interval', '-i', default=CANDLE_INTERVAL,
                        choices=['1h', '4h', '1d'],
                        help=f'K线周期 (默认: {CANDLE_INTERVAL})')
    parser.add_argument('--lookback', '-l', type=int, default=LOOKBACK_PERIOD,
                        help=f'MTM指标周期 (默认: {LOOKBACK_PERIOD})')
    parser.add_argument('--top', '-n', type=int, default=TOP_N_VOLUME,
                        help=f'交易量前N (默认: {TOP_N_VOLUME})')
    parser.add_argument('--save', action='store_true',
                        help='保存结果到JSON文件')
    parser.add_argument('--feishu', action='store_true',
                        help='推送结果到飞书')
    parser.add_argument('--schedule', action='store_true',
                        help='定时自动运行（自动扫描+自动推飞书）')
    args = parser.parse_args()

    # 定时模式
    if args.schedule:
        print(f"\n{'='*60}")
        print(f"  动量爆发筛选系统 - 定时运行模式")
        print(f"  周期: {args.interval} | 筛选范围: 前{args.top} | 自动推飞书{' + 保存JSON' if args.save else ''}")
        print(f"{'='*60}")

        # 启动时先执行一次
        print("\n[启动] 执行首次扫描...")
        run_scheduled_scan(args.interval, args.top, args.lookback, save=args.save)

        # 设置定时任务
        scheduler = setup_scheduler(args.interval, args.top, args.lookback, save=args.save)
        scheduler.start()
        print(f"\n[定时任务] 调度器已启动，等待下次自动扫描...")
        print(f"{'='*60}")
        print("系统运行中，按 Ctrl+C 停止\n")

        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\n\n[停止] 正在关闭系统...")
            scheduler.shutdown()
            print("[停止] 系统已安全关闭")
        return

    # 单次运行模式
    screener = MomentumScreener(
        interval=args.interval,
        lookback=args.lookback,
        top_n=args.top,
    )
    results = screener.run()

    if args.save:
        filename = f"screener_{args.interval}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        save_data = {
            'run_time': datetime.now().isoformat(),
            'interval': args.interval,
            'lookback': args.lookback,
            'top_n': args.top,
            'selected_count': len(results),
            'selected': results,
            'pre_selected': screener.pre_selected,
            'ema_stats': screener.ema_stats,
            'single_condition_hits': {
                'volume_expansion': screener.stat_symbols.get('volume_ok', []),
                'mtm_cross_up': screener.stat_symbols.get('mtm_cross_up', []),
                'mtm_cross_down': screener.stat_symbols.get('mtm_cross_down', []),
                'price_above_ema': screener.stat_symbols.get('price_above_ema', []),
                'price_below_ema': screener.stat_symbols.get('price_below_ema', []),
            },
        }
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(save_data, f, ensure_ascii=False, indent=2)
        print(f"\n结果已保存到: {filename}")

    if args.feishu:
        print("\n[飞书] 正在推送筛选报告...")
        screener.send_feishu_report()


if __name__ == "__main__":
    main()
