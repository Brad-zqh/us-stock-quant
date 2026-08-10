# Brad Quant: Multi-Factor Equity Research Platform

[![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Streamlit](https://img.shields.io/badge/Streamlit-App-FF4B4B?logo=streamlit&logoColor=white)](https://streamlit.io/)
[![Research Only](https://img.shields.io/badge/Use-Research%20Only-6A5ACD)](#limitations-and-disclaimer)

Brad Quant is a research-oriented, explainable multi-factor equity analysis platform for U.S. equities and China A-shares. It combines technical signals, company fundamentals, analyst expectations, capital flows, ownership structure, earnings quality, sector strength, and news sentiment in a unified screening and backtesting workflow.

Rather than attempting to predict exact future prices, the system ranks securities by their current multi-dimensional profile, converts the scores into interpretable signals, and attaches volatility-aware position sizing and risk controls.

**Live application:** [Open Brad Quant on Streamlit](https://us-stock-quant-txpjva2xepffh9h2peiaup.streamlit.app)

## Research Objectives

- Build an interpretable alternative to opaque stock-selection models.
- Compare heterogeneous signals across U.S. and Chinese equity markets.
- Evaluate ranking and timing rules through historical backtesting.
- Separate data acquisition, factor construction, portfolio logic, and presentation.
- Provide transparent signal attribution instead of treating model output as a black box.

## Key Capabilities

- **Multi-factor screening:** ranks watchlists, U.S. technology stocks, non-technology sectors, China A-share leaders, and index ETFs.
- **Cross-market data layer:** uses Futu OpenD when available and falls back to `yfinance`; China-specific data are supported through `akshare`.
- **Technical analysis:** SMA, EMA, MACD, RSI, Bollinger Bands, ATR, ADX/DI, KDJ, MFI, OBV, CMF, momentum, and 52-week breakout measures.
- **Fundamental and expectations data:** valuation, revenue growth, profitability, analyst ratings, target-price dispersion, and earnings revisions.
- **Alternative signals:** institutional ownership, insider ownership, short interest, earnings surprises, sector strength, and financial-news sentiment.
- **Risk management:** ATR-based stop levels, target levels, volatility-adjusted position sizing, and a per-security allocation cap.
- **Backtesting:** annualized return, Sharpe ratio, maximum drawdown, win rate, and strategy-versus-buy-and-hold comparisons.
- **Explainability:** plain-language attribution of bullish drivers, bearish risks, technical context, and model limitations.
- **Paper trading:** persistent simulated accounts, rule-based rebalancing, transaction logs, and equity curves.
- **Multi-platform delivery:** Streamlit web app plus PWA, Capacitor mobile shells, and Tauri desktop shells.

## Methodology

The composite score is calculated from 12 interpretable factor groups. The values below are relative weight units rather than final percentages; they are normalized at runtime, including when a data source or optional factor is unavailable.

| Factor | Relative weight | Representative inputs | Implementation |
|---|---:|---|---|
| Fundamentals | 14 | PEG, revenue growth, gross margin, ROE, net margin | `factors_plus.py` |
| Trend | 13 | Price relative to SMA50/SMA200, moving-average crossovers, ADX | `engine.py` |
| Analyst expectations | 11 | Consensus rating, target-price upside, analyst coverage | `factors_plus.py` |
| Momentum | 10 | MACD, one-month and six-month momentum, KDJ | `engine.py` |
| Earnings quality | 10 | Earnings surprises, earnings growth, forward EPS revisions | `factors_plus.py` |
| Money flow | 9 | OBV, Chaikin Money Flow, MFI, volume-confirmed breakouts | `factors_plus.py` |
| Ownership and positioning | 8 | Institutional ownership, insider ownership, short interest | `factors_plus.py` |
| Risk | 8 | Annualized volatility | `engine.py` |
| Relative strength | 7 | Performance relative to the market benchmark | `engine.py` |
| Sector strength | 6 | China industry breadth or U.S. sector-ETF momentum | `sector_factor.py` |
| News sentiment | 6 | VADER and market-specific financial sentiment lexicons | `news.py`, `cn_news.py` |
| Oscillator strength | 4 | RSI and Bollinger %B | `engine.py` |

The model also applies a market-regime adjustment based on benchmark trend and momentum. Risk-on conditions moderately increase composite scores, while risk-off conditions reduce them. This adjustment is intended to limit aggressive exposure during broad market deterioration.

### Signal Mapping

| Composite score | Signal | Interpretation |
|---:|---|---|
| 70 or above | Strong Buy | Broad positive factor agreement |
| 58–69 | Buy | Moderately positive profile |
| 45–57 | Hold | Mixed or neutral evidence |
| 35–44 | Reduce | Deteriorating factor profile |
| Below 35 | Sell | Broad negative factor agreement |

### Risk Rules

- Indicative stop level: current price minus `2.5 × ATR`.
- Indicative target level: current price plus `4 × ATR`.
- Position size: adjusted by composite score and realized volatility.
- Maximum allocation: 25% per security in the default paper-trading configuration.
- Near-term earnings events are flagged because of elevated gap risk.

## Application Modules

The Streamlit interface currently includes:

1. **Stock Details** — symbol and company-name search, candlestick charts, factor radar, news, risk levels, and backtests.
2. **Watchlist Ranking** — comparable scores, signals, risk levels, and factor heatmaps.
3. **Portfolio Backtest** — strategy-level evaluation of the current watchlist.
4. **AI Trader** — rule-based paper trading with optional LLM-generated research commentary.
5. **U.S. Technology Screener** — thematic screening across major technology groups.
6. **U.S. Sector Screener** — value, defensive, cyclical, healthcare, financial, consumer, energy, industrial, and communication groups.
7. **China A-Share Screener** — sector leaders across major Shanghai and Shenzhen industries.
8. **Index and ETF Screener** — U.S. and Chinese index timing and rotation analysis.
9. **Methodology** — an in-app explanation of the factors, signal rules, and limitations.

## Architecture

```text
Market data and metadata
        │
        ├── Futu OpenD / yfinance / akshare
        ▼
Feature and factor construction
        │
        ├── technical indicators
        ├── fundamentals and analyst expectations
        ├── earnings, ownership, sector, and sentiment signals
        ▼
Composite scoring and market-regime adjustment
        ▼
Risk rules, backtesting, and paper-trading logic
        ▼
Streamlit web interface and mobile/desktop shells
```

The analytical core is kept in plain Python modules so that factor calculations and portfolio logic can be tested independently of the user interface.

## Project Structure

| Path | Purpose |
|---|---|
| `engine.py` | Data orchestration, indicators, composite scoring, risk rules, and backtesting |
| `quotes.py` | Market-data abstraction with Futu-to-yfinance fallback |
| `factors_plus.py` | Fundamentals, analyst expectations, earnings quality, ownership, and money-flow factors |
| `sector_factor.py` | Sector-strength factor |
| `news.py`, `cn_news.py`, `futu_news.py` | Market-specific news acquisition and sentiment analysis |
| `universe.py`, `ashare.py`, `funds.py` | U.S. stocks, China A-shares, and ETF screening universes |
| `explain.py` | Human-readable signal attribution |
| `paper.py` | Paper-account state, valuation, transactions, and rebalancing |
| `futu_trader.py`, `futu_loop.py` | Optional Futu trading integration and scheduled execution |
| `app.py` | Streamlit application |
| `app-shell/` | PWA, Capacitor, and Tauri wrappers |

## Local Setup

### Requirements

- Python 3.11 or later
- Internet access for cloud market-data providers
- Optional: Futu OpenD on `127.0.0.1:11111` for local Futu market data or trading integration

### Installation

```bash
git clone https://github.com/Brad-zqh/us-stock-quant.git
cd us-stock-quant
python -m venv .venv
```

Activate the environment, then install dependencies and launch the app:

```bash
pip install -r requirements.txt
streamlit run app.py
```

Open `http://localhost:8501` in a browser.

## Configuration and Secrets

Copy `config.example.json` to `config.json` for optional local integrations. The local configuration file is excluded from Git and must never contain credentials intended for public distribution.

For Streamlit Cloud, store API keys and other credentials in Streamlit Secrets rather than in the repository. Supported optional integrations include LLM-generated commentary, email notifications, ServerChan notifications, and Futu OpenD.

## Data and Runtime Notes

- Daily bars and provider metadata may be delayed and should not be interpreted as real-time market data.
- Futu OpenD is preferred locally when available; the application silently falls back to `yfinance` when the gateway is unavailable.
- China A-share endpoints, especially news endpoints, may be slower or less reliable from overseas cloud infrastructure.
- Newly listed securities may not have enough observations for long-window indicators; the interface flags insufficient samples rather than treating missing values as valid signals.
- Streamlit Community Cloud may require a cold start after inactivity.

## Limitations and Disclaimer

This project is a quantitative research and software-engineering prototype. It is not a validated asset-pricing model, an execution guarantee, or a source of personalized investment advice. Backtest results are sensitive to the selected universe, data quality, transaction-cost assumptions, look-ahead controls, parameter choices, and market regime. Historical performance does not imply future performance.

Users are responsible for independently validating all data, assumptions, and outputs before applying any result outside a research environment.
