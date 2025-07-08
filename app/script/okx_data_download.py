#!/usr/bin/env python
# -*- coding: utf-8 -*-
# @Time    : 2024/01/21 15:26
# @Author  : shenglin.li
# @File    : script_binance_data_download.py
# @Software: PyCharm
import argparse
import csv
import datetime
import os
import sys
import time
from decimal import Decimal
from pathlib import Path

import tqdm
from okx import MarketData

# 添加项目路径到sys.path
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..'))

from app.core.config_manager import config_manager

api = MarketData.MarketAPI(domain="https://www.okx.com", flag="0", debug=False)


def download_okx_kline(start_date, end_date, symbols=None, intervals=None, skip=0, inst_type="SWAP", bar=None):
    if intervals is None:
        intervals = ["1H", "4H", "6H", "12H", "1m", "3m", "5m", "15m", "30m", "1D"]
    if symbols is None or len(symbols) == 0:
        tickers = api.get_tickers(instType=inst_type)
        symbols = []
        if tickers and tickers["code"] == "0":
            for ticker in tickers["data"]:
                if ticker["instId"].endswith("-USDT-" + inst_type):
                    symbols.append(ticker["instId"])
    symbols.sort()
    if bar:
        bar.total = len(symbols)
        bar.refresh()
    n = 0
    for symbol in symbols:
        if bar:
            bar.update(1)
        n += 1  
        if n < skip:
            continue
        __download_okx_kline(symbol, start_date, end_date, intervals, bar, inst_type)
        if bar:
            bar.set_postfix_str(f"成功下载 {n} 个交易对")


def __download_okx_kline(symbol, start_date, end_date, intervals, bar=None, inst_type="SWAP"):
    end_ts = int(datetime.datetime.strptime(end_date, '%Y-%m-%d').timestamp() * 1000) + 24 * 60 * 60 * 1000
    end_ts = min(end_ts, int(datetime.datetime.now().timestamp() * 1000))
    hour = 60 * 60 * 1000
    multi = {
        "1m": 1.5,
        "3m": 5,
        "5m": 8,
        "15m": 24,
        "30m": 50,
        "1H": 100,
        "4H": 400,
        "6H": 600,
        "12H": 1200,
        "1D": 2400,
    }
    tf = lambda x: datetime.datetime.fromtimestamp(x / 1000).strftime('%Y-%m-%d %H:%M')
    for interval in intervals:
        start_ts = find_real_start_ts(symbol, interval,
                                      int(datetime.datetime.strptime(start_date, '%Y-%m-%d').timestamp() * 1000),
                                      end_ts, int(hour * multi[interval]))

        while start_ts < end_ts:
            n = min(start_ts + int(hour * multi[interval]), end_ts)
            if bar:
                bar.set_postfix_str(f"{symbol} {interval} {tf(start_ts)} {tf(n)}")

            rows = get_data(symbol, interval, start_ts, n, bar=bar)
            rows.reverse()
            save_data(symbol, interval, rows, inst_type, bar)
            start_ts = n


def find_real_start_ts(symbol, interval, start_ts, end_ts, step):
    if (end_ts - start_ts) / step < 50:
        return start_ts
    max_find = 16
    left, right = start_ts, end_ts
    while max_find > 0 and left < right:
        max_find -= 1
        middle = int((left + right) / 2)
        rows = get_data(symbol, interval, left, middle)
        if len(rows) == 0:
            left = middle
        elif len(rows) == 100:
            right = middle
        else:
            break
    return left


def get_data(symbol, interval, start_ts, n, t=5, bar=None):
    try:
        candlesticks = api.get_history_candlesticks(symbol, before="%s" % (start_ts - 1), after="%s" % n,
                                                    bar=interval)
        if candlesticks is None or candlesticks["code"] != "0":
            if candlesticks:
                if bar:
                    bar.set_postfix_str(f"{symbol} {interval} {candlesticks['msg']}")
            raise Exception(candlesticks["msg"] if candlesticks else candlesticks)
        return candlesticks["data"]
    except Exception as e:
        if t > 0:
            time.sleep(0.3)
            return get_data(symbol, interval, start_ts, n, t - 1)
        else:
            raise e

client = None
def save_data(symbol, interval, rows, inst_type="SWAP", bar=None):
    """保存数据到ClickHouse数据库"""
    try:
        global client
        if client is None:
            from clickhouse_driver import Client
            from clickhouse_driver.errors import Error as ClickHouseError
            
            # 获取ClickHouse配置
            config = config_manager.get_config()
            if not config["is_configured"]:
                print("数据库未配置")
                return
            
            # 获取ClickHouse配置
            clickhouse_config = config.get("data_db")
            if not clickhouse_config:
                print("ClickHouse配置未找到")
                return
            
            # 创建ClickHouse客户端
            client = Client(
                host=clickhouse_config.get('host', '127.0.0.1'),
                port=clickhouse_config.get('port', 9000),
                user=clickhouse_config.get('user', 'default'),
                password=clickhouse_config.get('password', ''),
                database=clickhouse_config.get('database', 'default')
            )
        
        # 解析symbol获取quote_currency
        quote_currency = "USDT"  # 默认值
        if "-USDT-" in symbol:
            quote_currency = "USDT"
        elif "-BTC-" in symbol:
            quote_currency = "BTC"
        elif "-ETH-" in symbol:
            quote_currency = "ETH"
        
        # 转换inst_type为数字
        inst_type_map = {
            "SPOT": 1,
            "MARGIN": 2, 
            "SWAP": 3,
            "FUTURES": 4,
            "OPTION": 5
        }
        ins_type = inst_type_map.get(inst_type, 3)  # 默认SWAP
        
        # 准备插入数据
        insert_data = []
        for row in rows:
            if int(row[8]) == 1:  # 只保存已完成的K线
                insert_data.append({
                    'market': 'okx',
                    'timeframe': interval,
                    'timestamp': int(row[0]),
                    'symbol': symbol.split("-")[0],
                    'quote_currency': quote_currency,
                    'ins_type': ins_type,
                    'open': float(row[1]),
                    'high': float(row[2]),
                    'low': float(row[3]),
                    'close': float(row[4]),
                    'volume': float(row[5]),
                    'amount': float(row[7])
                })
        
        if insert_data:
            # 批量插入数据到ClickHouse
            batch_size = 1000
            for i in range(0, len(insert_data), batch_size):
                batch = insert_data[i:i + batch_size]
                
                # 准备数据
                data_to_insert = []
                for data in batch:
                    data_to_insert.append([
                        data['market'],
                        data['timeframe'],
                        data['timestamp'],
                        data['symbol'],
                        data['quote_currency'],
                        data['ins_type'],
                        data['open'],
                        data['high'],
                        data['low'],
                        data['close'],
                        data['volume'],
                        data['amount']
                    ])
                
                try:
                    # 执行插入
                    client.execute(
                        'INSERT INTO klines (market, timeframe, timestamp, symbol, quote_currency, ins_type, open, high, low, close, volume, amount) VALUES',
                        data_to_insert
                    )
                    if bar:
                        bar.set_postfix_str(f"成功插入 {len(data_to_insert)} 条数据")
                except ClickHouseError as e:
                    print(f"插入数据失败: {e}")
                    raise e
                    
    except ImportError:
        print("请安装 clickhouse-driver: pip install clickhouse-driver")
    except Exception as e:
        print(f"保存数据时出错: {e}")

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='OKX行情下载参数')

    # 定义期望接收的参数
    parser.add_argument('--start', type=str, default=datetime.datetime.now().strftime("%Y-%m-%d"))
    parser.add_argument('--end', type=str, default=datetime.datetime.now().strftime("%Y-%m-%d"))
    parser.add_argument('--inst_type', type=str, default="SWAP")
    parser.add_argument('--symbols', type=lambda x: x.split(','), default=[])
    parser.add_argument('--interval', type=lambda x: x.split(','),
                        default=["1H", "4H", "6H", "12H", "1m", "3m", "5m", "15m", "30m", "1D"])
    parser.add_argument('--skip', type=int, default=0)
    args = parser.parse_args()
    print("    start:", args.start)
    print("      end:", args.end)
    print("inst_type:", args.inst_type)
    print("  symbols:", args.symbols)
    print(" interval:", args.interval)
    print("     skip:", args.skip)
    # generate_kline_from_1m(args.start, args.end)
    bar = tqdm.tqdm(total=100, desc="OKX数据")
    download_okx_kline(args.start, args.end, symbols=args.symbols, intervals=args.interval, skip=args.skip,
                       inst_type=args.inst_type, bar=bar)

    # python okx_data_download.py --start=2024-03-01 --end=2024-04-02 --interval=5m --skip=7

"""
-- optimize table klines final
-- ck简单校验K线数量
with tsp as(SELECT arrayElement(array1, number) AS interval, arrayElement(array2, number) AS deta_ts FROM (select ['1m', '3m', '5m', '15m', '30m', '1H', '4H', '6H', '8H', '12H', '1D'] array1,[60000,180000,300000,900000,1800000,3600000,14400000,21600000,28800000,43200000,86400000] array2) a CROSS JOIN numbers(1, 11) AS n),
r as (select market, timeframe, symbol, quote_currency, ins_type, min(timestamp) start,max(timestamp) end, count(*) act from  klines group by market, timeframe, symbol, quote_currency, ins_type),
b as (select market, r.timeframe, symbol, quote_currency, ins_type, toDateTime(start/1000, 3),toDateTime(end/1000, 3), act, toInt64((end-start) / deta_ts) exp,deta_ts from r,tsp where r.timeframe=tsp.interval)

select * from b where act!= exp+1 

"""