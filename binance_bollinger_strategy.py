import ccxt
import time
from datetime import datetime, timezone
import pandas as pd
import ta

exchange = ccxt.binance({
    'apiKey': '',
    'secret': '',
    'enableRateLimit': True,
    'options': {'defaultType': 'future'}
})


symbol = 'BTC/USDT'
timeframe = '4h'
leverage = 2
position = None
entry_price = None
entry_low = None
entry_high = None


def fetch_data():
    ohlcv = exchange.fetch_ohlcv(symbol, timeframe, limit=100)
    df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    return df


def calculate_bollinger(df):
    bb = ta.volatility.BollingerBands(close=df['close'], window=20, window_dev=2)
    df['bb_upper'] = bb.bollinger_hband()
    df['bb_lower'] = bb.bollinger_lband()
    return df


def place_order(order_type, side, amount, price=None):
    params = {'positionSide': 'LONG' if side == 'buy' else 'SHORT'}
    if order_type == 'limit':
        order = exchange.create_limit_order(symbol, side, amount, price, params=params)
    else:
        order = exchange.create_market_order(symbol, side, amount, params=params)
    return order


def confirm_order_filled(order_id):
    for _ in range(10):
        order = exchange.fetch_order(order_id, symbol)
        if order['status'] == 'closed':
            return True
        time.sleep(2)
    return False


def get_balance():
    balance = exchange.fetch_balance({'type': 'future'})
    return balance['total']['USDT']


def calculate_amount(price):
    usdt_balance = get_balance()
    return round((usdt_balance * leverage) / price, 3)


def wait_until_next_candle():
    now = datetime.now(timezone.utc)
    next_hour = (now.hour // 4 + 1) * 4
    next_candle_time = now.replace(hour=next_hour % 24, minute=0, second=5, microsecond=0)
    if next_hour >= 24:
        next_candle_time += datetime.timedelta(days=1)
    sleep_time = (next_candle_time - now).total_seconds()
    print(f"[{now.strftime('%Y-%m-%d %H:%M:%S')}] 다음 4시간봉까지 {int(sleep_time // 60)}분 대기 중...")
    time.sleep(sleep_time)

def get_open_position():
    markets = exchange.load_markets()
    positions = exchange.fetch_positions()

    for pos in positions:
        if pos['symbol'] == 'BTC/USDT' and pos['contracts'] > 0:
            entry_price = float(pos['entryPrice'])
            entry_low = float(pos['info']['liquidationPrice']) if 'liquidationPrice' in pos['info'] else 0
            entry_high = float(pos['info']['markPrice']) if 'markPrice' in pos['info'] else 0
            side = 'long' if pos['side'] == 'long' else 'short'
            return side, entry_price, entry_low, entry_high

    return None, None, None, None



# 시작 시 기존 포지션 확인
position, entry_price, entry_low, entry_high = get_open_position()

# 메인 루프
while True:
    wait_until_next_candle()

    df = fetch_data()
    df = calculate_bollinger(df)

    last = df.iloc[-2]
    current = df.iloc[-1]

    mid = (last['open'] + last['close']) / 2
    price = current['close']
    amount = calculate_amount(price)

    if position is None:
        if mid > last['bb_upper']:
            order = place_order('limit', 'buy', amount, price)
            if confirm_order_filled(order['id']):
                position = 'long'
                entry_price = price
                entry_low = last['low']
                print(f"[{current['timestamp']}] Long 진입 @ {price}")
        elif mid < last['bb_lower']:
            order = place_order('limit', 'sell', amount, price)
            if confirm_order_filled(order['id']):
                position = 'short'
                entry_price = price
                entry_high = last['high']
                print(f"[{current['timestamp']}] Short 진입 @ {price}")

    elif position == 'long':
        if current['close'] < entry_low:
            place_order('market', 'sell', amount)
            position = None
            print(f"[{current['timestamp']}] Long 손절 @ {price}")
        elif current['open'] < last['bb_upper'] and current['close'] < last['bb_upper']:
            place_order('market', 'sell', amount)
            position = None
            print(f"[{current['timestamp']}] Long 익절 @ {price}")

    elif position == 'short':
        if current['close'] > entry_high:
            place_order('market', 'buy', amount)
            position = None
            print(f"[{current['timestamp']}] Short 손절 @ {price}")
        elif current['open'] > last['bb_lower'] and current['close'] > last['bb_lower']:
            place_order('market', 'buy', amount)
            position = None
            print(f"[{current['timestamp']}] Short 익절 @ {price}")
