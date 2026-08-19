# -*- coding: utf-8 -*-
"""
交易信号监控系统 - 配置文件
请根据你的实际需求修改以下配置
"""
import os
from dotenv import load_dotenv

# 加载 .env 配置文件（密钥等敏感信息放在 .env 中，不提交到代码库）
load_dotenv()

# ==================== 交易对配置 ====================
# 要监控的交易对列表（交易所格式）
WATCHLIST = [
    'BTC/USDT',      # 比特币
    'ETH/USDT',      # 以太坊
    'SOL/USDT',      # Solana
    'SNDKB/USDT',    # 闪迪（股票代币）
    'SKHYB/USDT',    # SK海力士（股票代币）
    'XAUT/USDT',     # Tether黄金
    'MUB/USDT',      # 美光科技（股票代币）
]

# 获取多少根K线用于形态识别
KLIMIT = 100

# ==================== 多周期监控配置 ====================
# 每个周期独立配置扫描时间和去重窗口
# key 为周期名称（如 '1h', '4h'），value 为该周期的配置
TIMEFRAME_CONFIGS = {
    '1h': {
        'enabled': True,                    # 是否启用
        'label': '1小时',                    # 显示名称
        # 扫描方式：'cron' = 定时cron表达式，'fixed' = 固定时间点，'interval' = 间隔
        'scan_mode': 'cron',
        # cron 表达式（每小时第55分钟扫描）
        'cron_minute': 55,                   # 每小时的第几分钟
        # 盘前预备提醒（提前多少分钟）
        'pre_reminder_minutes': 0,           # 1小时周期不需要盘前提醒
        # 去重时间窗口（分钟）：同一交易对同一形态在此时间内只提醒一次
        'deduplication_minutes': 60,         # 1小时
    },
    '4h': {
        'enabled': True,                    # 是否启用
        'label': '4小时',                    # 显示名称
        'scan_mode': 'fixed',               # 固定时间点扫描
        # 每天固定扫描时间列表（24小时制，北京时区）
        'fixed_times': [
            '08:00',   # 早盘提醒
            '12:00',   # 午间提醒
            '20:00',   # 晚间提醒
        ],
        # 盘前预备提醒（提前多少分钟）
        'pre_reminder_minutes': 15,
        # 去重时间窗口（分钟）
        'deduplication_minutes': 240,        # 4小时
    },
}

# 所有启用的周期列表（自动从 TIMEFRAME_CONFIGS 中生成，不用手动改）
ENABLED_TIMEFRAMES = [tf for tf, cfg in TIMEFRAME_CONFIGS.items() if cfg.get('enabled', False)]

# ==================== 数据源配置（多交易所自动降级） ====================
# 交易所列表，按优先级排序（第一个为主数据源，失败后自动尝试下一个）
# 支持的交易所ID（ccxt标准）: binance, gateio, okx, huobi, bybit, kucoin 等
EXCHANGE_LIST = [
    {
        'id': 'binance',         # 交易所ID（币安现货）
        'name': '币安',           # 显示名称
        'api_key': os.getenv('BINANCE_API_KEY', ''),
        'api_secret': os.getenv('BINANCE_API_SECRET', ''),
        'timeout': 10000,          # 超时时间（毫秒）
        'enableRateLimit': True,   # 启用速率限制
    },
    {
        'id': 'gate',
        'name': 'Gate.io',
        'api_key': os.getenv('GATE_API_KEY', ''),
        'api_secret': os.getenv('GATE_API_SECRET', ''),
        'timeout': 10000,
        'enableRateLimit': True,
    },
]

# 单个交易所失败后重试次数（每个交易所内重试）
EXCHANGE_RETRY_COUNT = 2

# 重试间隔（秒）
EXCHANGE_RETRY_INTERVAL = 1

# 交易对映射（不同交易所的交易对名称可能不同）
# 如果某个交易对在某个交易所的名称不同，在这里配置
# 例如：{'binance': {'BTC/USDT': 'BTC/USDT'}, 'gateio': {'BTC/USDT': 'BTC_USDT'}}
# 留空表示使用标准格式
SYMBOL_MAPPING = {}

# ==================== 形态识别配置 ====================
# 启用的形态列表
ENABLED_PATTERNS = [
    '流星线',        # 看跌 - 1根K线
    '乌云盖顶',      # 看跌 - 2根K线
    '黄昏之星',      # 看跌 - 3根K线
    '看跌吞没',      # 看跌 - 2根K线
    '刺透形态',      # 看涨 - 2根K线
    '早晨之星',      # 看涨 - 3根K线
    '看涨吞没',      # 看涨 - 2根K线
    '锤子线',        # 看涨 - 1根K线
]

# 形态确认阈值（实体深入比例，0.5 = 50%）
PATTERN_CONFIRMATION_RATIO = 0.5

# 小实体判定阈值（实体占K线总振幅的比例上限）
SMALL_BODY_RATIO = 0.35

# 长影线判定阈值（影线占实体的比例下限）
LONG_WICK_RATIO = 2.0

# 吞没形态力度倍数（第二根实体 / 第一根实体）
ENGULFING_STRENGTH_RATIO = 1.2

# 长实体判定（相对近期平均实体的倍数，用于晨星/暮星的第一根）
LONG_BODY_RATIO = 1.5

# 星线反转力度倍数（第三根实体 / 星线实体）
STAR_REVERSAL_RATIO = 2.0

# 短期高低点判断窗口（用于锤子线/流星线的位置确认，K线根数）
SWING_LOOKBACK = 5

# ==================== 飞书消息推送配置 ====================
# 是否启用飞书推送
ENABLE_FEISHU = True

# 飞书自定义机器人 Webhook 地址
# 如何获取：飞书群设置 -> 群机器人 -> 添加机器人 -> 自定义机器人 -> 复制Webhook地址
FEISHU_WEBHOOK_URL = os.getenv('FEISHU_WEBHOOK_URL', '')

# 飞书签名校验（如果机器人开启了签名校验，填写密钥）
FEISHU_SIGN_SECRET = os.getenv('FEISHU_SIGN_SECRET', '')

# 是否 @所有人
FEISHU_AT_ALL = False

# ==================== 桌面弹窗配置 ====================
# 是否启用桌面弹窗通知
ENABLE_DESKTOP_NOTIFY = True

# 弹窗停留时间（秒）
DESKTOP_NOTIFY_TIMEOUT = 10

# ==================== 网页仪表盘配置 ====================
# 是否启用网页仪表盘
ENABLE_WEB_DASHBOARD = True

# 仪表盘监听地址
WEB_HOST = '0.0.0.0'

# 仪表盘端口
WEB_PORT = 5000

# ==================== 信号记录配置 ====================
# 信号历史记录文件路径
SIGNAL_HISTORY_FILE = 'signal_history.json'

# 最大历史记录条数
MAX_HISTORY_SIGNALS = 1000
