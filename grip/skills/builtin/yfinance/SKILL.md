---
title: yfinance
description: Retrieve financial market data — stock prices, company fundamentals, historical charts, crypto, and portfolio analysis
category: finance
---
# yfinance

> Retrieve financial market data: stock prices, company fundamentals, historical charts, crypto, and portfolio analysis. Use when the user asks about stocks, investments, market data, ticker prices, portfolios, company financials, or cryptocurrency.

## Prerequisites

yfinance must be installed in the grip environment:

```bash
pip install yfinance
# or
uv pip install yfinance
```

All commands below use the `exec` tool to run Python one-liners or short scripts.

## Real-Time Stock Quotes

```python
import yfinance as yf

# Single ticker
ticker = yf.Ticker("AAPL")
info = ticker.info
print(f"Apple: ${info.get('currentPrice', 'N/A')}")
print(f"Day Range: ${info.get('dayLow')} - ${info.get('dayHigh')}")
print(f"52-Week Range: ${info.get('fiftyTwoWeekLow')} - ${info.get('fiftyTwoWeekHigh')}")
print(f"Market Cap: ${info.get('marketCap', 0):,.0f}")
print(f"P/E Ratio: {info.get('trailingPE', 'N/A')}")
print(f"Volume: {info.get('volume', 0):,}")
```

```python
# Multiple tickers at once
import yfinance as yf
tickers = yf.Tickers("AAPL MSFT GOOGL AMZN NVDA")
for symbol in ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA"]:
    info = tickers.tickers[symbol].info
    print(f"{symbol}: ${info.get('currentPrice', 'N/A'):>10} | P/E: {str(info.get('trailingPE', 'N/A')):>8} | Cap: ${info.get('marketCap', 0)/1e9:>7.1f}B")
```

## Historical Price Data (OHLCV)

```python
import yfinance as yf

ticker = yf.Ticker("AAPL")

# Period options: 1d, 5d, 1mo, 3mo, 6mo, 1y, 2y, 5y, 10y, ytd, max
# Interval options: 1m, 2m, 5m, 15m, 30m, 60m, 90m, 1h, 1d, 5d, 1wk, 1mo, 3mo
hist = ticker.history(period="1mo", interval="1d")
print(hist[["Open", "High", "Low", "Close", "Volume"]].tail(10).to_string())
```

```python
# Custom date range
hist = ticker.history(start="2024-01-01", end="2024-12-31")
print(f"2024 Return: {((hist['Close'].iloc[-1] / hist['Close'].iloc[0]) - 1) * 100:.1f}%")
```

## Company Fundamentals

```python
import yfinance as yf
ticker = yf.Ticker("MSFT")

# Income statement (annual)
income = ticker.income_stmt
print("Revenue:", income.loc["Total Revenue"].iloc[0] / 1e9, "B")
print("Net Income:", income.loc["Net Income"].iloc[0] / 1e9, "B")

# Balance sheet
balance = ticker.balance_sheet
print("Total Assets:", balance.loc["Total Assets"].iloc[0] / 1e9, "B")
print("Total Debt:", balance.loc["Total Debt"].iloc[0] / 1e9, "B")

# Cash flow
cashflow = ticker.cashflow
print("Operating CF:", cashflow.loc["Operating Cash Flow"].iloc[0] / 1e9, "B")
print("Free CF:", cashflow.loc["Free Cash Flow"].iloc[0] / 1e9, "B")
```

```python
# Quarterly financials
quarterly = ticker.quarterly_income_stmt
print(quarterly.loc["Total Revenue"].head(4).to_string())
```

## Dividends and Splits

```python
import yfinance as yf
ticker = yf.Ticker("AAPL")

# Dividend history
divs = ticker.dividends
print(divs.tail(8).to_string())
print(f"\nDividend Yield: {ticker.info.get('dividendYield', 0) * 100:.2f}%")

# Stock splits
splits = ticker.splits
print(splits[splits > 0].to_string())
```

## Cryptocurrency

Crypto tickers use the `-USD` suffix:

```python
import yfinance as yf

# Bitcoin
btc = yf.Ticker("BTC-USD")
print(f"Bitcoin: ${btc.info.get('currentPrice', 'N/A'):,.2f}")

# Ethereum
eth = yf.Ticker("ETH-USD")
print(f"Ethereum: ${eth.info.get('currentPrice', 'N/A'):,.2f}")

# Historical crypto data
hist = btc.history(period="7d", interval="1h")
print(hist[["Close"]].tail(24).to_string())
```

Common crypto tickers: `BTC-USD`, `ETH-USD`, `SOL-USD`, `ADA-USD`, `DOT-USD`, `DOGE-USD`, `XRP-USD`

## Portfolio Analysis

```python
import yfinance as yf

portfolio = {
    "AAPL": 50,    # 50 shares
    "MSFT": 30,
    "GOOGL": 20,
    "NVDA": 15,
}

total_value = 0
print(f"{'Symbol':<8} {'Shares':>8} {'Price':>10} {'Value':>12} {'Day %':>8}")
print("-" * 50)

for symbol, shares in portfolio.items():
    info = yf.Ticker(symbol).info
    price = info.get("currentPrice", 0)
    value = price * shares
    day_change = info.get("regularMarketChangePercent", 0)
    total_value += value
    print(f"{symbol:<8} {shares:>8} ${price:>9.2f} ${value:>11,.2f} {day_change:>7.2f}%")

print("-" * 50)
print(f"{'Total':<8} {'':>8} {'':>10} ${total_value:>11,.2f}")
```

## Index and ETF Data

```python
import yfinance as yf

# Major indices
indices = {"^GSPC": "S&P 500", "^DJI": "Dow Jones", "^IXIC": "NASDAQ", "^RUT": "Russell 2000"}
for symbol, name in indices.items():
    info = yf.Ticker(symbol).info
    print(f"{name}: {info.get('regularMarketPrice', 'N/A'):>10,.2f} ({info.get('regularMarketChangePercent', 0):>+.2f}%)")

# Popular ETFs
etfs = ["SPY", "QQQ", "VTI", "ARKK", "GLD", "TLT"]
for symbol in etfs:
    info = yf.Ticker(symbol).info
    print(f"{symbol}: ${info.get('currentPrice', 'N/A')}")
```

## Analyst Recommendations

```python
import yfinance as yf
ticker = yf.Ticker("NVDA")

# Analyst price targets
print(f"Target Mean: ${ticker.info.get('targetMeanPrice', 'N/A')}")
print(f"Target High: ${ticker.info.get('targetHighPrice', 'N/A')}")
print(f"Target Low: ${ticker.info.get('targetLowPrice', 'N/A')}")
print(f"Recommendation: {ticker.info.get('recommendationKey', 'N/A')}")

# Recent recommendations
recs = ticker.recommendations
if recs is not None:
    print(recs.tail(10).to_string())
```

## Error Handling

yfinance returns empty DataFrames or None for invalid tickers. Always check:

```python
import yfinance as yf
ticker = yf.Ticker("INVALID")
hist = ticker.history(period="5d")
if hist.empty:
    print("No data found. Check if the ticker symbol is correct.")
else:
    print(hist.to_string())
```

Common issues:
- Ticker not found → verify symbol on finance.yahoo.com
- Empty history → market may be closed or ticker delisted
- Missing info fields → not all fields available for all securities (especially crypto)
- Rate limiting → add `time.sleep(0.5)` between rapid successive calls
