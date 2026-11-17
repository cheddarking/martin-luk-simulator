# Replay Lab

An original offline Python/FastAPI simulator for studying a **mechanical daily swing** strategy against **actual historical US-stock daily prices**. The model is Martin Luk-style in the narrow sense of documented EMA/anchored-VWAP, support, risk and trade-management rules; it is not affiliated with anyone and does not assert what a person actually traded. Real market prices are kept in a **private local cache, outside the public repository**. Invented prices exist only in explicitly labelled regression fixtures and a legacy developer CLI, never as the default browser lesson.

## Purpose and boundaries

This Python application lets a user select real historical prices, inspect a deterministic mechanical-rule replay and audit modeled trades. It never places live orders, stores broker credentials or connects to a trading account.

**Data rights:** Yahoo Finance says its data must not be redistributed ([Yahoo Help](https://help.yahoo.com/kb/SLN2310.html)). This public project contains **no downloaded prices**. `history fetch` downloads only to a user-controlled private directory on a connected machine. Users are responsible for their data-provider terms; this software does not upload or package their price files.

## Install

Python 3.11+. In an offline environment, install the base/test dependencies from an available local PyPI mirror, **without the optional acquisition extra**:

```bash
python -m pip install -e '.[test]'
python -m pytest -q
python scripts/count_application_loc.py --min 1000
```

On a **connected personal machine only**, install the optional Yahoo/yfinance downloader if you want to backfill private prices:

```bash
python -m pip install -e '.[data]'
```

Browser tests were run locally with Python Playwright 1.58 and Chromium. Verify the browser installation in your own environment. CLI from source without install: `PYTHONPATH=src python -m luk_replay --help`.

## Acquire six years of daily prices privately

An existing two-year Yahoo/yfinance CSV cache can be used **read-only** with `--source-dir`. Its stock files use `Date,Close,High,Low,Open,Volume`. The default browser cache is `~/.local/share/luk-replay/history`, or `LUK_REPLAY_DATA_DIR` when set. Do not point the downloader at tracked source or a public repo directory. A `.local-data/` folder within this project is ignored, but the external home directory is the safer default.

For an explicit six-year backfill of five named symbols (example dates; update them for the day you run it):

```bash
python -m luk_replay history fetch \
  --symbols AAPL MSFT NVDA QQQ IWM \
  --start 2020-11-17 --end 2026-11-18 \
  --cache-dir ~/.local/share/luk-replay/history
```

`--end` is **exclusive**. A fetch reports **partial coverage as failure** (exit 3), not as six-year success. It does not overwrite an existing ticker CSV unless you pass `--replace`. Each private ticker has a `.meta.json` sidecar recording source, requested range, actual dates, adjustment setting, digest and corporate-action dates. The importer checks the sidecar digest before replay. The default set is bounded to five symbols; one invocation accepts at most ten to avoid bulk targeting. **No network call occurs in `history status`, `replay-daily`, or `serve`.**

The observed local acquisition on 17 November 2026 fetched **1,507 daily sessions per symbol from 17 November 2020 through 17 November 2026** for AAPL, MSFT, NVDA, QQQ and IWM in the private home cache; those price files are not in this repository. Yahoo could later change access, return fewer bars, or throttle requests. If the cache becomes stale, refresh it only by an explicit connected-machine command and review its coverage report.

[Yahoo/yfinance docs](https://ranaroussi.github.io/yfinance/reference/api/yfinance.download.html) say intraday history cannot extend past the last 60 days. This project targets **daily** six-year swing learning only. It never fabricates old intraday candles from daily OHLC.

## Replay offline

```bash
python -m luk_replay history status --source-dir ~/.local/share/luk-replay/history --symbols AAPL QQQ
python -m luk_replay replay-daily AAPL --source-dir ~/.local/share/luk-replay/history --no-store
python -m luk_replay serve --source-dir ~/.local/share/luk-replay/history --host 127.0.0.1 --port 8765
```

Open `http://127.0.0.1:8765`. Select a cached symbol and optional dates, then **Replay daily history**. The page lists the actual date range, source and price-adjustment policy; the chart, observation table and evidence trail derive from that private cached source. With no cache, it displays **Add private daily prices** setup instructions—not an invented stock chart. The server refuses non-loopback binding. `--no-store` avoids writing SQLite run history; ordinary replays save their event trail to a local SQLite DB. The optional `--start-date` retains earlier bars for indicator warmup, while `--end-date` caps simulated days.

For an **existing** local cache, pass its containing directory to `history status`, `replay-daily` or `serve`; do not copy its original screener's private code into this repo. In any offline environment, set `--source-dir` to a privately held price folder. Without real price files, the historical experience cannot be verified—do not report a fixture-driven test as a real-data run.

## Input and model contract

The daily CSV must contain exactly the columns `Date,Close,High,Low,Open,Volume`. Filename stem is the ticker (for example `AAPL.csv`), with ascending unique ISO `YYYY-MM-DD` trading dates. The importer derives session open/close in `America/New_York`, including historical daylight saving and early close. It rejects closed exchange dates and malformed prices; a provider-adjusted sub-cent OHLC value is rounded to the model's cent-per-stock convention, and **rounded cell count is recorded**. The original downloaded CSV remains private and unchanged. A six-year status is computed per ticker; IPOs or partial feeds are not labelled complete.

At the close of a completed daily session, the mechanical rule considers daily EMA alignment, an anchored-VWAP/support zone and risk gates. If it submits an order, its earliest possible fill is **the next exchange open**. The simulator applies a spread assumption because underlying-stock OHLC is not a Pepperstone bid/ask feed. For a held position, an opening gap beyond its stop uses the gap price. Where a daily bar touched both stop and target, the stop wins because daily OHLC cannot reveal which came first. Intrabar touches are **recorded at the bar's close**, not assigned a fictitious precise execution time. An armed EMA exit based on a completed daily close is placed for the **following open**—not retrospectively at 15:55.

For the broker-unit model: a `$115.04` equity quote corresponds to `11,504` spread-bet-style broker points; volume 10 represents **£0.10 per point**. GBP stake/risk and USD stock prices remain separate. Provider OHLC (requested with `auto_adjust=False`) may still reflect vendor corporate-action processing; `.meta.json` notes reported action dates, but this is **not** a point-in-time broker quote archive or a complete split/dividend/financing model. Dividend and split periods, market halts, FX, financing and exact order-book liquidity can materially change real fills or P&L. Treat results as educational modeled outcomes, never as an investment recommendation or verified historical trades.

The legacy intraday `replay` and synthetic `generate` CLI remain available for deterministic regression tests, but **are not the six-year learning path** and are not the default browser experience.

## Code map

- `src/luk_replay/ingest/daily_csv.py`, `history_catalog.py`, `yahoo_fetch.py`: daily source validation, provenance, private-cache discovery and explicit connected-machine acquisition.
- `src/luk_replay/engine/daily_replay.py`: completed-day decisions, next-open fills, conservative stop and following-open EMA exits.
- `src/luk_replay/domain`, `market`, `strategy`, `storage`: shared typed prices, calendar, risk, reason codes and SQLite audit history.
- `src/luk_replay/web`: locally served browser inspector; no CDN or market-data HTTP request.
- `tests`: invented test fixtures, Python/API tests and real local Chromium tests; no downloaded Yahoo price series.

## Verify

```bash
python -m pytest -q
python -m pytest -q tests/test_daily_import.py tests/test_daily_replay.py tests/test_history_catalog.py tests/test_yahoo_fetch.py
python -m pytest -q tests/browser/test_replay.py
python -m compileall -q src/luk_replay
python scripts/count_application_loc.py --min 1000
```

Browser tests must run in actual Chromium. A passing mocked fetch test does not prove Yahoo was reachable; a local six-year coverage report does not prove that a different machine has the same private cache. State those boundaries explicitly when reporting results.

## License

Application source and invented test fixtures are released under the [MIT License](LICENSE). Market-price files in the private cache are **not** part of that license or this repository.
