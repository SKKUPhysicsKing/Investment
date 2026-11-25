# Investment — 주가 시계열 수집

Yahoo Finance의 주가 이력을 받아 **시간순 pandas DataFrame, CSV, SQLite**로 저장하는 Python 프로젝트입니다. API 키 없이 종목 티커, 기간, 봉 간격을 지정할 수 있습니다. 기본 조회는 최근 1년의 일봉입니다.

- 미국 주식과 Yahoo에 등록된 한국 주식 조회
- 시가·고가·저가·종가·수정종가·거래량, 배당·분할 이벤트
- UTC 시각과 거래소 현지 날짜를 함께 보존
- CSV마다 조회 조건·통화·시간대·수집 시각을 JSON으로 기록
- SQLite 재수집 시 중복 없이 갱신
- 입력 오류, 빈 데이터, 네트워크 오류 처리와 제한된 재시도

## 설치

Python 3.10 이상이 필요합니다.

```bash
git clone https://github.com/SKKUPhysicsKing/Investment.git
cd Investment
python -m venv .venv
```

Windows PowerShell에서 가상환경을 활성화합니다.

```powershell
.venv\Scripts\Activate.ps1
```

macOS/Linux에서는 `source .venv/bin/activate`를 실행합니다. 이후 공통으로:

```bash
python -m pip install -e .
```

## 명령줄에서 가져오기

### 애플의 2024년 일봉

```bash
investment fetch AAPL --start 2024-01-01 --end 2025-01-01 -o data/AAPL_2024.csv
```

`--start`는 포함하고 **`--end`는 포함하지 않습니다.** 위 명령은 거래소 현지 날짜로 2024-01-01 이상, 2025-01-01 미만의 봉을 조회합니다. 휴장일을 임의로 생성하거나 보간하지 않습니다.

### 삼성전자 최근 1년

```bash
investment fetch 005930.KS --period 1y -o data/samsung_1y.csv
```

### 최근 5일의 5분봉

```bash
investment fetch MSFT --period 5d --interval 5m -o data/MSFT_5m.csv
```

### SQLite에도 누적 저장

```bash
investment fetch AAPL --period 1y --db data/prices.sqlite
```

기본 CSV 이름은 `data/AAPL_1d.csv`입니다. 같은 CSV를 다시 쓰려면 `--overwrite`를 명시합니다.

```bash
investment fetch AAPL --period 1y --db data/prices.sqlite --overwrite
```

기간은 `--period` 또는 `--start`/`--end` 중 한 방식으로 지정합니다. `--start`만 지정하면 현재까지 조회하며, `--end`만 지정할 수는 없습니다. `python -m investment fetch ...`도 같은 기능을 제공합니다.

| 항목 | 사용법 |
| --- | --- |
| 티커 | 회사명 대신 Yahoo 티커 사용: `AAPL`, `MSFT`, `005930.KS` |
| 한국 주식 | 보통 코스피 `.KS`, 코스닥 `.KQ`; Yahoo에서 실제 티커 확인 |
| 조회 기간 | `1d`, `5d`, `1mo`, `3mo`, `6mo`, `1y`, `2y`, `5y`, `10y`, `ytd`, `max` |
| 봉 간격 | `1m`, `2m`, `5m`, `15m`, `30m`, `60m`, `90m`, `1h`, `1d`, `5d`, `1wk`, `1mo`, `3mo` |
| 시간 외 거래 | `--prepost`로 요청, 거래소·종목·간격에 따라 가용성 상이 |
| 네트워크 | `--timeout 15 --attempts 3`; 시도 횟수 1~5, 요청별 timeout |
| 도움말 | `investment fetch --help` |

분봉의 과거 조회 범위는 Yahoo의 제한을 받으며 간격에 따라 다릅니다. 오래된 분봉을 조회하다 실패하면 최근의 짧은 기간으로 다시 요청하세요. 이 프로젝트는 과거 전 기간의 분봉이나 실시간 시세를 보장하지 않습니다.

## Python에서 사용

```python
from investment import fetch_prices, save_csv, save_sqlite

history = fetch_prices("AAPL", start="2024-01-01", end="2025-01-01")
df = history.data

# 분석용 시계열: UTC DatetimeIndex, 오름차순
close = df.set_index("timestamp")["close"]
print(close.head())

save_csv(history, "data/AAPL_2024.csv")
save_sqlite(history, "data/prices.sqlite")
print(history.metadata["currency"])
```

전체 예제는 [examples/download_prices.py](examples/download_prices.py)에 있습니다. 여러 종목은 `fetch_prices`를 종목별로 호출하고 같은 SQLite 파일에 저장하면 됩니다.

## 데이터 형식

| 열 | 의미 |
| --- | --- |
| `timestamp` | 봉의 시각. DataFrame은 UTC timezone-aware datetime, CSV는 ISO 8601 `+00:00` |
| `date` | 거래소 현지 시간 기준 봉의 날짜 `YYYY-MM-DD` |
| `symbol` | 정규화된 Yahoo 티커 |
| `open`, `high`, `low`, `close` | Yahoo OHLC, yfinance의 추가 자동 조정 비활성화 |
| `adj_close` | Yahoo가 제공하는 수정종가. 미제공 시 결측값 유지 |
| `volume` | 거래량. nullable 정수, 미제공 시 결측값 유지 |
| `dividends` | 해당 봉의 배당 이벤트 값, 이벤트가 없으면 0 |
| `stock_splits` | 해당 봉의 분할 이벤트 비율, 이벤트가 없으면 0 |

한국 일봉의 현지 자정은 UTC로 전날 15시입니다. 따라서 일봉을 날짜로 묶거나 엑셀에서 확인할 때는 `date` 열을 사용하세요. 주봉·월봉의 날짜는 해당 봉의 라벨이며 개별 거래일을 뜻하지 않습니다.

OHLC는 `auto_adjust=False`, `repair=False`로 요청합니다. Yahoo 자체의 분할 반영 방식은 그대로 따르므로 완전히 무조정된 체결 이력과 동일하다고 가정해서는 안 됩니다. 수익률 분석 시 목적에 맞게 `close` 또는 `adj_close`를 선택하세요. 가격의 통화는 JSON의 `currency`에 기록하며, 자동 환산하지 않습니다.

OHLC가 결측인 행은 제거하고, 중복 시각은 마지막 행을 유지한 뒤 오름차순으로 정렬합니다. 제거한 행 수는 메타데이터 `cleaning`에 기록합니다. 결측 수정종가나 거래량을 0 또는 종가로 대체하지 않습니다.

### CSV와 메타데이터

`AAPL_2024.csv`와 `AAPL_2024.csv.metadata.json`을 함께 생성합니다. CSV는 엑셀에서 열 수 있는 UTF-8 BOM 형식입니다. 메타데이터에는 출처, 라이브러리 버전, 원래 요청, 통화, 거래소 시간대, 수집 시각, 데이터 범위, 행 수를 기록합니다. 각 파일은 개별적으로 원자적으로 저장하며, 두 파일 전체나 CSV/SQLite 사이를 묶는 트랜잭션은 아닙니다.

### SQLite

`prices` 테이블의 `(source, symbol, interval, prepost, timestamp)`가 고유 키입니다. 같은 조건의 같은 봉은 갱신하고, 다른 종목·간격·시간 외 거래 설정은 별도로 보존합니다. `fetch_runs` 테이블에는 각 수집의 메타데이터를 기록합니다.

재조회는 요청한 범위 전체를 다시 가져와 갱신합니다. 배당·분할 등으로 과거 수정종가가 바뀔 수 있으므로 최신 값만 추가하는 방식으로 생기는 불일치를 줄일 수 있습니다. 이번에 다시 조회하지 않은 기간은 기존 값이 유지됩니다. 장중의 마지막 봉은 아직 확정되지 않았을 수 있습니다.

```sql
SELECT date, close, adj_close, volume, currency
FROM prices
WHERE symbol = 'AAPL' AND interval = '1d' AND prepost = 0 AND source = 'yahoo'
ORDER BY timestamp;
```

## 개발과 검증

```bash
python -m pip install -e ".[dev]"
ruff check .
ruff format --check .
pytest -q
python -m build
```

테스트는 네트워크 없이 날짜 경계, 한국/미국 시간대, DST, 중복·결측 처리, 재시도, CSV 보호, SQLite 갱신을 검증합니다. GitHub Actions는 Python 3.10/3.12/3.13에서 같은 검증과 패키지 빌드를 실행합니다. 실제 Yahoo 연결은 위 명령줄 예제로 별도 확인할 수 있습니다.

## 데이터 출처

이 프로젝트는 [yfinance](https://ranaroussi.github.io/yfinance/)를 통해 Yahoo Finance 데이터를 요청합니다. yfinance는 Yahoo의 공식 SDK가 아니며, 가용성과 요청 제한은 서비스 상황에 따라 달라집니다. 다운로드한 데이터는 저장소에 커밋하지 않습니다. 데이터 이용 범위는 [Yahoo 이용 약관](https://legal.yahoo.com/us/en/yahoo/terms/otos/index.html)을 확인하세요.

- [yfinance history API와 날짜·조정 옵션](https://ranaroussi.github.io/yfinance/reference/yfinance.price_history.html)
- [Yahoo Finance 종목 검색](https://finance.yahoo.com/)
