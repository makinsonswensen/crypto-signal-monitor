# -*- coding: utf-8 -*-
"""
K线形态识别模块（加密市场适配版）
适配7x24小时连续交易的加密市场，去掉跳空缺口等不适用的硬条件

看涨形态：
- 锤子线 (Hammer) - 1根K线，底部反转
- 看涨吞没 (Bullish Engulfing) - 2根K线
- 刺透形态 (Piercing Pattern) - 2根K线（简化版：只判断收盘价深入）
- 早晨之星 (Morning Star) - 3根K线（适配版：去掉跳空）

看跌形态：
- 流星线 (Shooting Star) - 1根K线，顶部反转
- 乌云盖顶 (Dark Cloud Cover) - 2根K线（简化版：只判断收盘价深入）
- 看跌吞没 (Bearish Engulfing) - 2根K线
- 黄昏之星 (Evening Star) - 3根K线（适配版：去掉跳空）
"""
import config


# ==================== 基础工具函数 ====================

def is_bullish(candle):
    """判断是否为阳线"""
    return candle['close'] > candle['open']


def is_bearish(candle):
    """判断是否为阴线"""
    return candle['close'] < candle['open']


def body_size(candle):
    """计算实体大小"""
    return abs(candle['close'] - candle['open'])


def candle_range(candle):
    """计算K线总振幅（最高价-最低价）"""
    return candle['high'] - candle['low']


def upper_wick_size(candle):
    """计算上影线长度"""
    if is_bullish(candle):
        return candle['high'] - candle['close']
    else:
        return candle['high'] - candle['open']


def lower_wick_size(candle):
    """计算下影线长度"""
    if is_bullish(candle):
        return candle['open'] - candle['low']
    else:
        return candle['close'] - candle['low']


def is_small_body(candle):
    """判断是否为小实体"""
    rng = candle_range(candle)
    if rng == 0:
        return False
    return body_size(candle) / rng <= config.SMALL_BODY_RATIO


def is_long_lower_wick(candle):
    """判断是否有长下影线"""
    bs = body_size(candle)
    if bs == 0:
        return False
    return lower_wick_size(candle) / bs >= config.LONG_WICK_RATIO


def is_long_upper_wick(candle):
    """判断是否有长上影线"""
    bs = body_size(candle)
    if bs == 0:
        return False
    return upper_wick_size(candle) / bs >= config.LONG_WICK_RATIO


def body_high(candle):
    """获取实体上沿"""
    return max(candle['open'], candle['close'])


def body_low(candle):
    """获取实体下沿"""
    return min(candle['open'], candle['close'])


def avg_body_size(candles, n=10):
    """计算最近n根K线的平均实体大小"""
    if len(candles) < n:
        n = len(candles)
    recent = candles[-n:]
    total = sum(body_size(c) for c in recent)
    return total / n if n > 0 else 0


def is_swing_low(candles, lookback=None):
    """
    判断最后一根K线是否为短期低点（最低价是lookback根内最低）
    candles: 包含至少lookback+1根K线的列表，最后一根是当前K线
    """
    if lookback is None:
        lookback = config.SWING_LOOKBACK

    if len(candles) < lookback + 1:
        return False

    current_low = candles[-1]['low']
    # 往前看lookback根
    for i in range(2, lookback + 2):
        if len(candles) - i < 0:
            break
        if candles[-i]['low'] < current_low:
            return False
    return True


def is_swing_high(candles, lookback=None):
    """
    判断最后一根K线是否为短期高点（最高价是lookback根内最高）
    """
    if lookback is None:
        lookback = config.SWING_LOOKBACK

    if len(candles) < lookback + 1:
        return False

    current_high = candles[-1]['high']
    for i in range(2, lookback + 2):
        if len(candles) - i < 0:
            break
        if candles[-i]['high'] > current_high:
            return False
    return True


# ==================== 看涨形态 ====================

def detect_hammer(candles):
    """
    锤子线（看涨）- 1根K线

    加密市场适配版：
    - 小实体（实体/全振幅 ≤ 35%）
    - 长下影线（≥ 实体的2倍）
    - 上影线很短（≤ 实体的0.6倍）
    - 出现在短期低点（最近5根内最低价）
    """
    if len(candles) < config.SWING_LOOKBACK + 1:
        return False

    c = candles[-1]

    # 小实体
    if not is_small_body(c):
        return False

    # 长下影线
    if not is_long_lower_wick(c):
        return False

    # 上影线很短
    bs = body_size(c)
    if bs == 0:
        return False
    if upper_wick_size(c) > bs * 0.6:
        return False

    # 短期低点位置确认
    if not is_swing_low(candles):
        return False

    return True


def detect_bullish_engulfing(candles):
    """
    看涨吞没（看涨）- 2根K线

    加密市场适配版：
    - 第一根阴线，第二根阳线
    - 第二根阳线实体完全覆盖第一根阴线实体
    - 第二根实体 ≥ 第一根实体的 1.2 倍（力度确认）
    """
    if len(candles) < 2:
        return False

    first = candles[-2]
    second = candles[-1]

    # 第一根阴线，第二根阳线
    if not is_bearish(first) or not is_bullish(second):
        return False

    # 第二根实体完全覆盖第一根实体
    if body_low(second) >= body_low(first):
        return False
    if body_high(second) <= body_high(first):
        return False

    # 力度确认：第二根实体 ≥ 第一根的 ENGULFING_STRENGTH_RATIO 倍
    first_bs = body_size(first)
    second_bs = body_size(second)
    if first_bs == 0:
        return False
    if second_bs / first_bs < config.ENGULFING_STRENGTH_RATIO:
        return False

    return True


def detect_piercing_pattern(candles):
    """
    刺透形态（看涨）- 2根K线

    加密市场简化版：
    - 第一根阴线，第二根阳线
    - 第二根收盘价深入第一根实体超过50%（从下往上算）
    - 收盘价不超过第一根实体顶部
    - （去掉了跳空低开的要求，只判断收盘位置）
    """
    if len(candles) < 2:
        return False

    first = candles[-2]
    second = candles[-1]

    # 第一根阴线，第二根阳线
    if not is_bearish(first) or not is_bullish(second):
        return False

    first_body_low = body_low(first)
    first_body_high = body_high(first)
    first_body_size = first_body_high - first_body_low

    if first_body_size == 0:
        return False

    # 收盘价深入第一根实体超过设定比例（从下往上算）
    target_price = first_body_low + first_body_size * config.PATTERN_CONFIRMATION_RATIO
    if second['close'] <= target_price:
        return False

    # 收盘价不超过第一根实体顶部
    if second['close'] >= first_body_high:
        return False

    return True


def detect_morning_star(candles):
    """
    早晨之星（看涨）- 3根K线

    加密市场适配版：
    - 第一根：长阴线（实体 ≥ 过去10根平均实体的1.5倍）
    - 第二根：小实体星线，实体整体位于第一根实体的下半部分
    - 第三根：阳线，实体深入第一根实体超过50%（从下往上）
    - 第三根实体 ≥ 星线实体的 2 倍（反转力度确认）
    """
    if len(candles) < 3:
        return False

    first = candles[-3]
    second = candles[-2]
    third = candles[-1]

    # 第一根阴线
    if not is_bearish(first):
        return False

    # 第一根是长阴线（相对近期平均实体）
    avg_bs = avg_body_size(candles[:-1], n=10)  # 不含当前这根
    if avg_bs == 0:
        return False
    if body_size(first) / avg_bs < config.LONG_BODY_RATIO:
        return False

    # 第三根阳线
    if not is_bullish(third):
        return False

    # 第二根是小实体（星线）
    if not is_small_body(second):
        return False

    # 第二根实体位于第一根实体的下半部分
    # 判断：星线实体的中点 < 第一根实体的中点
    second_mid = (body_high(second) + body_low(second)) / 2
    first_mid = (body_high(first) + body_low(first)) / 2
    if second_mid >= first_mid:
        return False

    # 第三根实体深入第一根实体超过设定比例（从下往上）
    first_body_low = body_low(first)
    first_body_high = body_high(first)
    first_body_size_val = first_body_high - first_body_low
    if first_body_size_val == 0:
        return False

    target_price = first_body_low + first_body_size_val * config.PATTERN_CONFIRMATION_RATIO
    if third['close'] <= target_price:
        return False

    # 第三根实体顶部不超过第一根实体顶部
    if body_high(third) >= first_body_high:
        return False

    # 反转力度：第三根实体 ≥ 星线实体的 STAR_REVERSAL_RATIO 倍
    second_bs = body_size(second)
    third_bs = body_size(third)
    if second_bs == 0:
        return False
    if third_bs / second_bs < config.STAR_REVERSAL_RATIO:
        return False

    return True


# ==================== 看跌形态 ====================

def detect_shooting_star(candles):
    """
    流星线（看跌）- 1根K线

    加密市场适配版：
    - 小实体（实体/全振幅 ≤ 35%）
    - 长上影线（≥ 实体的2倍）
    - 下影线很短（≤ 实体的0.6倍）
    - 出现在短期高点（最近5根内最高价）
    """
    if len(candles) < config.SWING_LOOKBACK + 1:
        return False

    c = candles[-1]

    # 小实体
    if not is_small_body(c):
        return False

    # 长上影线
    if not is_long_upper_wick(c):
        return False

    # 下影线很短
    bs = body_size(c)
    if bs == 0:
        return False
    if lower_wick_size(c) > bs * 0.6:
        return False

    # 短期高点位置确认
    if not is_swing_high(candles):
        return False

    return True


def detect_bearish_engulfing(candles):
    """
    看跌吞没（看跌）- 2根K线

    加密市场适配版：
    - 第一根阳线，第二根阴线
    - 第二根阴线实体完全覆盖第一根阳线实体
    - 第二根实体 ≥ 第一根实体的 1.2 倍（力度确认）
    """
    if len(candles) < 2:
        return False

    first = candles[-2]
    second = candles[-1]

    # 第一根阳线，第二根阴线
    if not is_bullish(first) or not is_bearish(second):
        return False

    # 第二根实体完全覆盖第一根实体
    if body_high(second) <= body_high(first):
        return False
    if body_low(second) >= body_low(first):
        return False

    # 力度确认：第二根实体 ≥ 第一根的 ENGULFING_STRENGTH_RATIO 倍
    first_bs = body_size(first)
    second_bs = body_size(second)
    if first_bs == 0:
        return False
    if second_bs / first_bs < config.ENGULFING_STRENGTH_RATIO:
        return False

    return True


def detect_dark_cloud_cover(candles):
    """
    乌云盖顶（看跌）- 2根K线

    加密市场简化版：
    - 第一根阳线，第二根阴线
    - 第二根收盘价深入第一根实体超过50%（从上往下算）
    - 收盘价不低于第一根实体底部
    - （去掉了跳空高开的要求，只判断收盘位置）
    """
    if len(candles) < 2:
        return False

    first = candles[-2]
    second = candles[-1]

    # 第一根阳线，第二根阴线
    if not is_bullish(first) or not is_bearish(second):
        return False

    first_body_low = body_low(first)
    first_body_high = body_high(first)
    first_body_size_val = first_body_high - first_body_low

    if first_body_size_val == 0:
        return False

    # 收盘价深入第一根实体超过设定比例（从上往下算）
    target_price = first_body_high - first_body_size_val * config.PATTERN_CONFIRMATION_RATIO
    if second['close'] >= target_price:
        return False

    # 收盘价不低于第一根实体底部
    if second['close'] <= first_body_low:
        return False

    return True


def detect_evening_star(candles):
    """
    黄昏之星（看跌）- 3根K线

    加密市场适配版：
    - 第一根：长阳线（实体 ≥ 过去10根平均实体的1.5倍）
    - 第二根：小实体星线，实体整体位于第一根实体的上半部分
    - 第三根：阴线，实体深入第一根实体超过50%（从上往下）
    - 第三根实体 ≥ 星线实体的 2 倍（反转力度确认）
    """
    if len(candles) < 3:
        return False

    first = candles[-3]
    second = candles[-2]
    third = candles[-1]

    # 第一根阳线
    if not is_bullish(first):
        return False

    # 第一根是长阳线（相对近期平均实体）
    avg_bs = avg_body_size(candles[:-1], n=10)
    if avg_bs == 0:
        return False
    if body_size(first) / avg_bs < config.LONG_BODY_RATIO:
        return False

    # 第三根阴线
    if not is_bearish(third):
        return False

    # 第二根是小实体（星线）
    if not is_small_body(second):
        return False

    # 第二根实体位于第一根实体的上半部分
    # 判断：星线实体的中点 > 第一根实体的中点
    second_mid = (body_high(second) + body_low(second)) / 2
    first_mid = (body_high(first) + body_low(first)) / 2
    if second_mid <= first_mid:
        return False

    # 第三根实体深入第一根实体超过设定比例（从上往下）
    first_body_low = body_low(first)
    first_body_high = body_high(first)
    first_body_size_val = first_body_high - first_body_low
    if first_body_size_val == 0:
        return False

    target_price = first_body_high - first_body_size_val * config.PATTERN_CONFIRMATION_RATIO
    if third['close'] >= target_price:
        return False

    # 第三根实体底部不低于第一根实体底部
    if body_low(third) <= first_body_low:
        return False

    # 反转力度：第三根实体 ≥ 星线实体的 STAR_REVERSAL_RATIO 倍
    second_bs = body_size(second)
    third_bs = body_size(third)
    if second_bs == 0:
        return False
    if third_bs / second_bs < config.STAR_REVERSAL_RATIO:
        return False

    return True


# ==================== 形态注册表 ====================

PATTERN_REGISTRY = {
    '锤子线': {
        'direction': '看涨',
        'candles': 1,
        'detector': detect_hammer,
        'description': '长下影线小实体，短期低点反转信号',
    },
    '看涨吞没': {
        'direction': '看涨',
        'candles': 2,
        'detector': detect_bullish_engulfing,
        'description': '阳线实体完全覆盖前一根阴线实体',
    },
    '刺透形态': {
        'direction': '看涨',
        'candles': 2,
        'detector': detect_piercing_pattern,
        'description': '阳线收盘深入阴线实体内部50%+',
    },
    '早晨之星': {
        'direction': '看涨',
        'candles': 3,
        'detector': detect_morning_star,
        'description': '长阴+星线+长阳，底部反转形态',
    },
    '流星线': {
        'direction': '看跌',
        'candles': 1,
        'detector': detect_shooting_star,
        'description': '长上影线小实体，短期高点反转信号',
    },
    '乌云盖顶': {
        'direction': '看跌',
        'candles': 2,
        'detector': detect_dark_cloud_cover,
        'description': '阴线收盘深入阳线实体内部50%+',
    },
    '看跌吞没': {
        'direction': '看跌',
        'candles': 2,
        'detector': detect_bearish_engulfing,
        'description': '阴线实体完全覆盖前一根阳线实体',
    },
    '黄昏之星': {
        'direction': '看跌',
        'candles': 3,
        'detector': detect_evening_star,
        'description': '长阳+星线+长阴，顶部反转形态',
    },
}


def scan_patterns(df, enabled_patterns=None):
    """
    扫描K线数据，检测所有启用的形态

    Args:
        df: K线数据DataFrame
        enabled_patterns: 启用的形态名称列表，为None则使用配置

    Returns:
        list: 检测到的形态列表
    """
    if enabled_patterns is None:
        enabled_patterns = config.ENABLED_PATTERNS

    if df is None or len(df) < 3:
        return []

    # 将DataFrame转换为字典列表（最近的在最后）
    candles = []
    for idx, row in df.iterrows():
        candles.append({
            'timestamp': idx,
            'open': float(row['open']),
            'high': float(row['high']),
            'low': float(row['low']),
            'close': float(row['close']),
            'volume': float(row['volume']),
        })

    detected = []

    for pattern_name in enabled_patterns:
        if pattern_name not in PATTERN_REGISTRY:
            continue

        pattern_info = PATTERN_REGISTRY[pattern_name]
        detector = pattern_info['detector']

        try:
            if detector(candles):
                last_candle = candles[-1]
                detected.append({
                    'pattern': pattern_name,
                    'direction': pattern_info['direction'],
                    'description': pattern_info['description'],
                    'candles_count': pattern_info['candles'],
                    'close_price': last_candle['close'],
                    'timestamp': last_candle['timestamp'],
                })
        except Exception as e:
            print(f"[形态检测异常] {pattern_name}: {e}")

    return detected


if __name__ == '__main__':
    from data_fetcher import get_data_fetcher

    fetcher = get_data_fetcher()
    df = fetcher.fetch_ohlcv('BTC/USDT', '1h', limit=100)

    if df is not None:
        results = scan_patterns(df)
        print(f"检测到 {len(results)} 个形态:")
        for r in results:
            print(f"  - {r['pattern']} ({r['direction']}): {r['description']}")
            print(f"    价格: {r['close_price']:.2f}, 时间: {r['timestamp']}")
    else:
        print("获取数据失败")
