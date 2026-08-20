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


def calculate_atr(candles, period=14):
    """
    计算 ATR（平均真实波幅），用于衡量波动率
    返回最后一根K线对应的ATR值
    """
    if len(candles) < period + 1:
        return None

    tr_values = []
    for i in range(1, len(candles)):
        curr = candles[i]
        prev = candles[i - 1]

        high = curr['high']
        low = curr['low']
        prev_close = prev['close']

        tr1 = high - low
        tr2 = abs(high - prev_close)
        tr3 = abs(low - prev_close)
        tr = max(tr1, tr2, tr3)
        tr_values.append(tr)

    # 简单移动平均
    if len(tr_values) < period:
        return None

    recent_tr = tr_values[-period:]
    atr = sum(recent_tr) / period
    return atr


def calculate_ema(candles, period=20):
    """
    计算 EMA（指数移动平均）
    返回最后一根K线对应的EMA值
    """
    if len(candles) < period:
        return None

    # 初始值用 SMA
    closes = [c['close'] for c in candles]
    sma = sum(closes[:period]) / period

    # EMA 平滑系数
    multiplier = 2 / (period + 1)
    ema = sma

    for i in range(period, len(closes)):
        ema = closes[i] * multiplier + ema * (1 - multiplier)

    return ema


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

    优化版（六层过滤）：
    1. 小实体（形态学）：实体 / 全振幅 ≤ 35%
    2. 小实体（ATR绝对）：实体 < 0.3 × ATR
    3. 长下影线：下影线 / 实体 ≥ 2倍 且 下影线 > 1.0×ATR
    4. 短上影线：上影线 / 实体 ≤ 0.6倍
    5. EMA20趋势过滤：收盘价在 EMA20 下方（下降趋势中反转才有效）
    6. 位置确认：最低价是最近5根内最低价（短期低点）
    """
    min_required = max(
        config.ATR_PERIOD + 1,
        config.HAMMER_SHOOTINGSTAR_EMA_PERIOD + 1,
        config.SWING_LOOKBACK + 1,
        30
    )
    if len(candles) < min_required:
        return False

    c = candles[-1]

    # ===== 第一层：小实体（形态学）=====
    if not is_small_body(c):
        return False

    bs = body_size(c)
    if bs == 0:
        return False

    # ===== 第二层：小实体（ATR绝对判定）=====
    atr = calculate_atr(candles, period=config.ATR_PERIOD)
    if atr is None or atr == 0:
        return False

    if bs >= config.HAMMER_SHOOTINGSTAR_BODY_ATR_MAX_RATIO * atr:
        return False

    # ===== 第三层：长下影线（相对 + 绝对）=====
    if not is_long_lower_wick(c):
        return False

    lower_wick = lower_wick_size(c)
    if lower_wick < config.HAMMER_SHOOTINGSTAR_WICK_ATR_RATIO * atr:
        return False

    # ===== 第四层：短上影线 =====
    if upper_wick_size(c) > bs * 0.6:
        return False

    # ===== 第五层：EMA20 趋势过滤 =====
    ema = calculate_ema(candles[:-1], period=config.HAMMER_SHOOTINGSTAR_EMA_PERIOD)
    if ema is None:
        return False

    # 锤子线必须出现在下降趋势中（价格在EMA下方）
    if c['close'] >= ema:
        return False

    # ===== 第六层：位置确认（短期低点）=====
    if not is_swing_low(candles):
        return False

    return True


def detect_bullish_engulfing(candles):
    """
    看涨吞没（看涨）- 2根K线

    Gemini优化版（力度调整为1.1倍）：
    1. 趋势过滤：价格处于 EMA20 下方（下降趋势中反转才有效）
    2. ATR波动率过滤：当前K线实体 > 0.8×ATR（反转有力度）
    3. 相对力度：当前K线实体 / 前一根实体 ≥ 1.1倍
    4. 形态基础：前阴后阳，收盘高于前开
    5. 开盘容忍：开盘价 ≤ 前收盘价 × 1.005（允许0.5%微小偏差）
    """
    min_required = max(
        config.ATR_PERIOD + 1,
        config.ENGULFING_EMA_PERIOD + 1,
        30
    )
    if len(candles) < min_required:
        return False

    first = candles[-2]
    second = candles[-1]

    # 基础形态：前一根阴线，第二根阳线
    if not is_bearish(first) or not is_bullish(second):
        return False

    first_bs = body_size(first)
    second_bs = body_size(second)

    if first_bs == 0:
        return False

    # ===== 过滤器 A：ATR 波动率过滤 =====
    atr = calculate_atr(candles, period=config.ATR_PERIOD)
    if atr is None or atr == 0:
        return False

    # 当前K线实体必须足够大（> 0.8 * ATR）
    if second_bs <= config.ENGULFING_CURR_BODY_ATR_RATIO * atr:
        return False

    # ===== 过滤器 B：相对力度 =====
    # 当前K线实体 / 前一根实体 ≥ 设定倍数
    if second_bs / first_bs < config.ENGULFING_STRENGTH_RATIO:
        return False

    # ===== 过滤器 C：EMA20 趋势过滤 =====
    # 用形态前（前一根时）的数据计算EMA，确认处于下降趋势
    ema = calculate_ema(candles[:-1], period=config.ENGULFING_EMA_PERIOD)
    if ema is None:
        return False

    # 看涨吞没必须出现在下降趋势中（价格在EMA下方）
    if first['close'] >= ema:
        return False

    # ===== 核心形态逻辑 =====
    # 开盘容忍：开盘价 ≤ 前收盘价 × (1 + 容忍比例)
    # 加密市场无跳空，允许微小偏差
    if first['close'] == 0:
        return False
    if second['open'] > first['close'] * (1 + config.ENGULFING_OPEN_TOLERANCE):
        return False

    # 收盘确认：收盘价 > 前一根开盘价（实体被吞没）
    if second['close'] <= first['open']:
        return False

    return True


def detect_piercing_pattern(candles):
    """
    刺透形态（看涨）- 2根K线

    加密市场进阶版（Gemini优化，三重过滤降噪）：
    
    1. 趋势过滤：价格处于 EMA20 下方（下降趋势中出现的反转才有效）
    2. 波动率过滤：前一根实体 > 1.2倍ATR，当前实体 > 0.8倍ATR（过滤震荡十字星）
    3. 动作确认：今日最低价曾跌破昨日最低价（完成砸盘诱空），然后收回
    4. 深度确认：收盘价深入前一根阴线实体 50% 以上，但不突破开盘价（未变成吞没）
    """
    if len(candles) < max(config.ATR_PERIOD + 1, config.PIERCING_DARKCLOUD_EMA_PERIOD, 30):
        return False

    first = candles[-2]
    second = candles[-1]

    # 基础形态：前一根阴线，后一根阳线
    if not is_bearish(first) or not is_bullish(second):
        return False

    # ===== 过滤器 A：大K线过滤（基于ATR） =====
    atr = calculate_atr(candles, period=config.ATR_PERIOD)
    if atr is None or atr == 0:
        return False

    # 前一根必须是大阴线（实体 > 1.2 * ATR）
    if body_size(first) <= config.PIERCING_DARKCLOUD_PREV_BODY_ATR_RATIO * atr:
        return False

    # 当前K线实体也要有足够力度（> 0.8 * ATR）
    if body_size(second) <= config.PIERCING_DARKCLOUD_CURR_BODY_ATR_RATIO * atr:
        return False

    # ===== 过滤器 B：趋势过滤（基于EMA20） =====
    # 取前一根K线时的EMA值（用到前一根为止的数据计算）
    # 用全部数据计算EMA，取倒数第二根对应的EMA值（即形态形成前的趋势状态）
    ema = calculate_ema(candles[:-1], period=config.PIERCING_DARKCLOUD_EMA_PERIOD)
    if ema is None:
        return False

    # 刺透形态必须出现在下降趋势中（价格在EMA下方）
    if first['close'] >= ema:
        return False

    # ===== 核心逻辑：刺透形态 =====
    first_body_low = body_low(first)
    first_body_high = body_high(first)
    first_body_size_val = first_body_high - first_body_low

    if first_body_size_val == 0:
        return False

    # 动作确认：今日最低价曾跌破昨日最低价（砸盘诱空）
    if second['low'] >= first['low']:
        return False

    # 深度确认：收盘价深入第一根实体超过设定比例（从下往上算）
    target_price = first_body_low + first_body_size_val * config.PATTERN_CONFIRMATION_RATIO
    if second['close'] <= target_price:
        return False

    # 边界确认：收盘价不超过第一根实体顶部（未变成完全吞没）
    if second['close'] >= first_body_high:
        return False

    return True


def detect_morning_star(candles):
    """
    早晨之星（看涨）- 3根K线

    合并优化版（Gemini + 当前版优势）：
    1. 趋势过滤：价格处于 EMA20 下方（下降趋势末端才有效）
    2. ATR动态衡量：C1 > 1.0×ATR（大阴线确立趋势），C3 > 0.8×ATR（反转有力度）
    3. 星线双重验证：小实体（相对比例35%）+ ATR上限（0.3倍）+ 动量衰竭（收盘接近前收）
    4. 位置确认：星线位于第一根实体下半区
    5. 深度确认：第三根深入第一根实体 50% 以上
    6. 反转力度：C3实体 / 星线实体 ≥ 2倍
    7. 非吞没边界：第三根不超过第一根顶部（保持形态互斥）
    """
    min_required = max(
        config.ATR_PERIOD + 1,
        config.STAR_PATTERN_EMA_PERIOD + 1,
        30
    )
    if len(candles) < min_required:
        return False

    first = candles[-3]
    second = candles[-2]
    third = candles[-1]

    # ===== 基础形态 =====
    # 第一根阴线，第三根阳线
    if not is_bearish(first) or not is_bullish(third):
        return False

    # ===== 过滤器 A：ATR 动态大K线过滤 =====
    # 用形态前的数据计算ATR（避免未来函数）
    atr_c1 = calculate_atr(candles[:-2], period=config.ATR_PERIOD)
    atr_c3 = calculate_atr(candles, period=config.ATR_PERIOD)

    if atr_c1 is None or atr_c3 is None or atr_c1 == 0 or atr_c3 == 0:
        return False

    # C1必须是大阴线（实体 > 1.0 * ATR）
    if body_size(first) <= config.STAR_PATTERN_C1_BODY_ATR_RATIO * atr_c1:
        return False

    # C3必须是大阳线（实体 > 0.8 * ATR）
    if body_size(third) <= config.STAR_PATTERN_C3_BODY_ATR_RATIO * atr_c3:
        return False

    # ===== 过滤器 B：EMA20 趋势过滤 =====
    # 用形态前（C1时）的数据计算EMA，确认当时处于下降趋势
    ema_c1 = calculate_ema(candles[:-2], period=config.STAR_PATTERN_EMA_PERIOD)
    if ema_c1 is None:
        return False

    # 早晨之星必须出现在下降趋势中（价格在EMA下方）
    if first['close'] >= ema_c1:
        return False

    # ===== 星线双重验证 =====
    # 验证1：小实体（相对自身振幅比例 ≤ 35%）- 形态学意义
    if not is_small_body(second):
        return False

    # 验证2：ATR上限（实体 < 0.3 * ATR）- 波动率过滤
    atr_c2 = calculate_atr(candles[:-1], period=config.ATR_PERIOD)
    if atr_c2 is None or atr_c2 == 0:
        return False
    if body_size(second) >= config.STAR_PATTERN_C2_BODY_ATR_MAX_RATIO * atr_c2:
        return False

    # 验证3：动量衰竭 - 星线收盘价接近第一根收盘价（±1%以内）
    # 说明价格跌到低位后走平了，空头动量耗尽
    if first['close'] == 0:
        return False
    price_deviation = abs(second['close'] - first['close']) / abs(first['close'])
    if price_deviation > config.STAR_PATTERN_MOMENTUM_EXHAUSTION_RATIO:
        return False

    # 验证4：位置确认 - 星线实体中点位于第一根实体下半区
    second_mid = (body_high(second) + body_low(second)) / 2
    first_mid = (body_high(first) + body_low(first)) / 2
    if second_mid >= first_mid:
        return False

    # ===== 核心逻辑：深度 + 力度 + 边界 =====
    first_body_low = body_low(first)
    first_body_high = body_high(first)
    first_body_size_val = first_body_high - first_body_low

    if first_body_size_val == 0:
        return False

    # 深度确认：第三根收盘价深入第一根实体超过设定比例（从下往上）
    target_price = first_body_low + first_body_size_val * config.PATTERN_CONFIRMATION_RATIO
    if third['close'] <= target_price:
        return False

    # 非吞没边界：第三根实体顶部不超过第一根实体顶部（未变成完全吞没）
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

    优化版（六层过滤）：
    1. 小实体（形态学）：实体 / 全振幅 ≤ 35%
    2. 小实体（ATR绝对）：实体 < 0.3 × ATR
    3. 长上影线：上影线 / 实体 ≥ 2倍 且 上影线 > 1.0×ATR
    4. 短下影线：下影线 / 实体 ≤ 0.6倍
    5. EMA20趋势过滤：收盘价在 EMA20 上方（上升趋势中反转才有效）
    6. 位置确认：最高价是最近5根内最高价（短期高点）
    """
    min_required = max(
        config.ATR_PERIOD + 1,
        config.HAMMER_SHOOTINGSTAR_EMA_PERIOD + 1,
        config.SWING_LOOKBACK + 1,
        30
    )
    if len(candles) < min_required:
        return False

    c = candles[-1]

    # ===== 第一层：小实体（形态学）=====
    if not is_small_body(c):
        return False

    bs = body_size(c)
    if bs == 0:
        return False

    # ===== 第二层：小实体（ATR绝对判定）=====
    atr = calculate_atr(candles, period=config.ATR_PERIOD)
    if atr is None or atr == 0:
        return False

    if bs >= config.HAMMER_SHOOTINGSTAR_BODY_ATR_MAX_RATIO * atr:
        return False

    # ===== 第三层：长上影线（相对 + 绝对）=====
    if not is_long_upper_wick(c):
        return False

    upper_wick = upper_wick_size(c)
    if upper_wick < config.HAMMER_SHOOTINGSTAR_WICK_ATR_RATIO * atr:
        return False

    # ===== 第四层：短下影线 =====
    if lower_wick_size(c) > bs * 0.6:
        return False

    # ===== 第五层：EMA20 趋势过滤 =====
    ema = calculate_ema(candles[:-1], period=config.HAMMER_SHOOTINGSTAR_EMA_PERIOD)
    if ema is None:
        return False

    # 流星线必须出现在上升趋势中（价格在EMA上方）
    if c['close'] <= ema:
        return False

    # ===== 第六层：位置确认（短期高点）=====
    if not is_swing_high(candles):
        return False

    return True


def detect_bearish_engulfing(candles):
    """
    看跌吞没（看跌）- 2根K线

    Gemini优化版（力度调整为1.1倍）：
    1. 趋势过滤：价格处于 EMA20 上方（上升趋势中反转才有效）
    2. ATR波动率过滤：当前K线实体 > 0.8×ATR（反转有力度）
    3. 相对力度：当前K线实体 / 前一根实体 ≥ 1.1倍
    4. 形态基础：前阳后阴，收盘低于前开
    5. 开盘容忍：开盘价 ≥ 前收盘价 × 0.995（允许0.5%微小偏差）
    """
    min_required = max(
        config.ATR_PERIOD + 1,
        config.ENGULFING_EMA_PERIOD + 1,
        30
    )
    if len(candles) < min_required:
        return False

    first = candles[-2]
    second = candles[-1]

    # 基础形态：前一根阳线，第二根阴线
    if not is_bullish(first) or not is_bearish(second):
        return False

    first_bs = body_size(first)
    second_bs = body_size(second)

    if first_bs == 0:
        return False

    # ===== 过滤器 A：ATR 波动率过滤 =====
    atr = calculate_atr(candles, period=config.ATR_PERIOD)
    if atr is None or atr == 0:
        return False

    # 当前K线实体必须足够大（> 0.8 * ATR）
    if second_bs <= config.ENGULFING_CURR_BODY_ATR_RATIO * atr:
        return False

    # ===== 过滤器 B：相对力度 =====
    # 当前K线实体 / 前一根实体 ≥ 设定倍数
    if second_bs / first_bs < config.ENGULFING_STRENGTH_RATIO:
        return False

    # ===== 过滤器 C：EMA20 趋势过滤 =====
    # 用形态前（前一根时）的数据计算EMA，确认处于上升趋势
    ema = calculate_ema(candles[:-1], period=config.ENGULFING_EMA_PERIOD)
    if ema is None:
        return False

    # 看跌吞没必须出现在上升趋势中（价格在EMA上方）
    if first['close'] <= ema:
        return False

    # ===== 核心形态逻辑 =====
    # 开盘容忍：开盘价 ≥ 前收盘价 × (1 - 容忍比例)
    # 加密市场无跳空，允许微小偏差
    if first['close'] == 0:
        return False
    if second['open'] < first['close'] * (1 - config.ENGULFING_OPEN_TOLERANCE):
        return False

    # 收盘确认：收盘价 < 前一根开盘价（实体被吞没）
    if second['close'] >= first['open']:
        return False

    return True


def detect_dark_cloud_cover(candles):
    """
    乌云盖顶（看跌）- 2根K线

    加密市场进阶版（Gemini优化，三重过滤降噪）：
    
    1. 趋势过滤：价格处于 EMA20 上方（上升趋势中出现的反转才有效）
    2. 波动率过滤：前一根实体 > 1.2倍ATR，当前实体 > 0.8倍ATR（过滤震荡十字星）
    3. 动作确认：今日最高价曾突破昨日最高价（完成冲高诱多），然后回落
    4. 深度确认：收盘价深入前一根阳线实体 50% 以下，但不跌破开盘价（未变成吞没）
    """
    if len(candles) < max(config.ATR_PERIOD + 1, config.PIERCING_DARKCLOUD_EMA_PERIOD, 30):
        return False

    first = candles[-2]
    second = candles[-1]

    # 基础形态：前一根阳线，后一根阴线
    if not is_bullish(first) or not is_bearish(second):
        return False

    # ===== 过滤器 A：大K线过滤（基于ATR） =====
    atr = calculate_atr(candles, period=config.ATR_PERIOD)
    if atr is None or atr == 0:
        return False

    # 前一根必须是大阳线（实体 > 1.2 * ATR）
    if body_size(first) <= config.PIERCING_DARKCLOUD_PREV_BODY_ATR_RATIO * atr:
        return False

    # 当前K线实体也要有足够力度（> 0.8 * ATR）
    if body_size(second) <= config.PIERCING_DARKCLOUD_CURR_BODY_ATR_RATIO * atr:
        return False

    # ===== 过滤器 B：趋势过滤（基于EMA20） =====
    # 用前一根K线为止的数据计算EMA（形态形成前的趋势状态）
    ema = calculate_ema(candles[:-1], period=config.PIERCING_DARKCLOUD_EMA_PERIOD)
    if ema is None:
        return False

    # 乌云盖顶必须出现在上升趋势中（价格在EMA上方）
    if first['close'] <= ema:
        return False

    # ===== 核心逻辑：乌云盖顶 =====
    first_body_low = body_low(first)
    first_body_high = body_high(first)
    first_body_size_val = first_body_high - first_body_low

    if first_body_size_val == 0:
        return False

    # 动作确认：今日最高价曾突破昨日最高价（冲高诱多）
    if second['high'] <= first['high']:
        return False

    # 深度确认：收盘价深入第一根实体超过设定比例（从上往下算）
    target_price = first_body_high - first_body_size_val * config.PATTERN_CONFIRMATION_RATIO
    if second['close'] >= target_price:
        return False

    # 边界确认：收盘价不低于第一根实体底部（未变成完全吞没）
    if second['close'] <= first_body_low:
        return False

    return True


def detect_evening_star(candles):
    """
    黄昏之星（看跌）- 3根K线

    合并优化版（Gemini + 当前版优势）：
    1. 趋势过滤：价格处于 EMA20 上方（上升趋势末端才有效）
    2. ATR动态衡量：C1 > 1.0×ATR（大阳线确立趋势），C3 > 0.8×ATR（反转有力度）
    3. 星线双重验证：小实体（相对比例35%）+ ATR上限（0.3倍）+ 动量衰竭（收盘接近前收）
    4. 位置确认：星线位于第一根实体上半区
    5. 深度确认：第三根深入第一根实体 50% 以上
    6. 反转力度：C3实体 / 星线实体 ≥ 2倍
    7. 非吞没边界：第三根不跌破第一根底部（保持形态互斥）
    """
    min_required = max(
        config.ATR_PERIOD + 1,
        config.STAR_PATTERN_EMA_PERIOD + 1,
        30
    )
    if len(candles) < min_required:
        return False

    first = candles[-3]
    second = candles[-2]
    third = candles[-1]

    # ===== 基础形态 =====
    # 第一根阳线，第三根阴线
    if not is_bullish(first) or not is_bearish(third):
        return False

    # ===== 过滤器 A：ATR 动态大K线过滤 =====
    atr_c1 = calculate_atr(candles[:-2], period=config.ATR_PERIOD)
    atr_c3 = calculate_atr(candles, period=config.ATR_PERIOD)

    if atr_c1 is None or atr_c3 is None or atr_c1 == 0 or atr_c3 == 0:
        return False

    # C1必须是大阳线（实体 > 1.0 * ATR）
    if body_size(first) <= config.STAR_PATTERN_C1_BODY_ATR_RATIO * atr_c1:
        return False

    # C3必须是大阴线（实体 > 0.8 * ATR）
    if body_size(third) <= config.STAR_PATTERN_C3_BODY_ATR_RATIO * atr_c3:
        return False

    # ===== 过滤器 B：EMA20 趋势过滤 =====
    ema_c1 = calculate_ema(candles[:-2], period=config.STAR_PATTERN_EMA_PERIOD)
    if ema_c1 is None:
        return False

    # 黄昏之星必须出现在上升趋势中（价格在EMA上方）
    if first['close'] <= ema_c1:
        return False

    # ===== 星线双重验证 =====
    # 验证1：小实体（相对自身振幅比例 ≤ 35%）- 形态学意义
    if not is_small_body(second):
        return False

    # 验证2：ATR上限（实体 < 0.3 * ATR）- 波动率过滤
    atr_c2 = calculate_atr(candles[:-1], period=config.ATR_PERIOD)
    if atr_c2 is None or atr_c2 == 0:
        return False
    if body_size(second) >= config.STAR_PATTERN_C2_BODY_ATR_MAX_RATIO * atr_c2:
        return False

    # 验证3：动量衰竭 - 星线收盘价接近第一根收盘价（±1%以内）
    # 说明价格涨到高位后走平了，多头顶量耗尽
    if first['close'] == 0:
        return False
    price_deviation = abs(second['close'] - first['close']) / abs(first['close'])
    if price_deviation > config.STAR_PATTERN_MOMENTUM_EXHAUSTION_RATIO:
        return False

    # 验证4：位置确认 - 星线实体中点位于第一根实体上半区
    second_mid = (body_high(second) + body_low(second)) / 2
    first_mid = (body_high(first) + body_low(first)) / 2
    if second_mid <= first_mid:
        return False

    # ===== 核心逻辑：深度 + 力度 + 边界 =====
    first_body_low = body_low(first)
    first_body_high = body_high(first)
    first_body_size_val = first_body_high - first_body_low

    if first_body_size_val == 0:
        return False

    # 深度确认：第三根收盘价深入第一根实体超过设定比例（从上往下）
    target_price = first_body_high - first_body_size_val * config.PATTERN_CONFIRMATION_RATIO
    if third['close'] >= target_price:
        return False

    # 非吞没边界：第三根实体底部不低于第一根实体底部（未变成完全吞没）
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
        'description': 'EMA20趋势过滤+ATR波动率过滤，六层过滤的底部反转信号',
    },
    '看涨吞没': {
        'direction': '看涨',
        'candles': 2,
        'detector': detect_bullish_engulfing,
        'description': 'EMA20趋势过滤+ATR波动率过滤，前阴后阳收盘越前开，力度1.1倍',
    },
    '刺透形态': {
        'direction': '看涨',
        'candles': 2,
        'detector': detect_piercing_pattern,
        'description': '下降趋势中大阴线后阳线深入50%+，ATR+EMA双重过滤',
    },
    '早晨之星': {
        'direction': '看涨',
        'candles': 3,
        'detector': detect_morning_star,
        'description': '长阴+星线+长阳，EMA20趋势过滤+ATR动态衡量+动量衰竭确认',
    },
    '流星线': {
        'direction': '看跌',
        'candles': 1,
        'detector': detect_shooting_star,
        'description': 'EMA20趋势过滤+ATR波动率过滤，六层过滤的顶部反转信号',
    },
    '乌云盖顶': {
        'direction': '看跌',
        'candles': 2,
        'detector': detect_dark_cloud_cover,
        'description': '上升趋势中大阳线后阴线深入50%+，ATR+EMA双重过滤',
    },
    '看跌吞没': {
        'direction': '看跌',
        'candles': 2,
        'detector': detect_bearish_engulfing,
        'description': 'EMA20趋势过滤+ATR波动率过滤，前阳后阴收盘破前开，力度1.1倍',
    },
    '黄昏之星': {
        'direction': '看跌',
        'candles': 3,
        'detector': detect_evening_star,
        'description': '长阳+星线+长阴，EMA20趋势过滤+ATR动态衡量+动量衰竭确认',
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
