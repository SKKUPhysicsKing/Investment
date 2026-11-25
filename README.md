# Investment — 주가 시계열 앱

**회사명 검색 → 기간 입력 → 주가 그래프 → CSV 내보내기**를 제공하는 Windows 데스크톱 앱입니다. 실행할 때 GitHub `main`의 최신 코드를 확인하고 자동으로 설치합니다. 기존 Python API와 명령줄 수집 기능도 사용할 수 있습니다.

## Windows에서 앱 실행

Python 3.10 이상(Tcl/Tk 포함)이 한 번 설치되어 있어야 합니다. 이미 이 프로젝트의 CLI를 실행한 Windows PC라면 일반적으로 그대로 사용할 수 있습니다.

1. [최신 프로젝트 ZIP 다운로드](https://github.com/SKKUPhysicsKing/Investment/archive/refs/heads/main.zip)
2. ZIP을 원하는 앱 폴더에 **압축 해제**합니다.
3. 그 폴더의 **`StartInvestment.cmd`를 더블클릭**합니다.
4. 첫 실행은 필요한 패키지를 설치하므로 몇 분 걸릴 수 있습니다. 준비가 끝나면 앱 창이 열립니다.

Git 설치, 가상환경 활성화, PowerShell 실행 정책 변경, Yahoo 로그인, API 키 입력은 필요하지 않습니다. ZIP 안에서 바로 실행하지 말고 먼저 압축을 해제하세요.

기존 `Investment` 폴더를 그대로 사용하려면 PowerShell에서 아래 두 파일만 받은 뒤 실행해도 됩니다. 소스 전체는 런처가 내려받습니다.

```powershell
Invoke-WebRequest "https://raw.githubusercontent.com/SKKUPhysicsKing/Investment/main/launch_app.py" -OutFile launch_app.py
Invoke-WebRequest "https://raw.githubusercontent.com/SKKUPhysicsKing/Investment/main/StartInvestment.cmd" -OutFile StartInvestment.cmd
.\StartInvestment.cmd
```

## 앱 사용법

1. 왼쪽에서 `삼성전자`, `에코프로비엠`, `Apple`, `애플`, `AAPL` 같은 회사명/티커를 검색합니다. 한국 기업은 KRX KIND 상장 목록, 해외 기업은 Yahoo 검색을 사용합니다. 해외 기업의 한국어 이름은 애플·엔비디아·마이크로소프트·테슬라·아마존·구글·메타·브로드컴 별칭을 지원하며, 그 밖의 해외 기업은 영문명 또는 티커를 입력하세요.
2. 검색 결과에서 **원하는 회사와 티커**를 선택합니다. 이름이 비슷한 회사나 다른 시장의 종목을 구분할 수 있습니다.
3. 시작일/종료일을 `YYYY-MM-DD`로 입력하고 봉 간격을 선택한 뒤 **조회 · PLOT**을 누릅니다. **앱의 시작일과 종료일은 모두 포함**합니다. 일봉·주봉·월봉·1/5/15/30분봉·1시간봉을 지원합니다.
4. 그래프에서 종가/수정종가와 거래량을 확인합니다. 아래 도구 모음으로 확대·이동·그래프 저장을 할 수 있습니다. 데이터 표 탭은 최근 500행까지 표시합니다.
5. **CSV 내보내기**를 누르면 **앱 실행 폴더의 `data` 폴더**에 조회한 전체 데이터를 저장합니다. 저장 전에는 CSV를 만들지 않습니다. **data 폴더 열기**로 저장한 파일을 확인합니다.

예: `Investment/StartInvestment.cmd`로 실행하면 `Investment/data/005930.KS_2026-01-02_2026-11-25_1d.csv`와 같은 이름으로 저장합니다. 날짜는 실제 반환된 첫/마지막 봉 기준이며 같은 파일명이 있으면 `_2`, `_3`을 붙여 기존 파일을 보존합니다. 기존 CLI와 같은 11개 열 및 JSON 메타데이터를 저장합니다. 그래프의 종가/수정종가 선택과 관계없이 CSV에는 두 열을 모두 담습니다.

검색어·날짜를 바꿔도 새로 조회하기 전에는 기존 그래프가 유지됩니다. 내보내기는 **현재 표시 중인 데이터**를 기준으로 하며 회사명·실제 데이터 범위·봉 수를 그래프 위에 표시합니다. 조회 중에도 창이 응답하며, 실패하면 기존 그래프를 보존하고 오류를 안내합니다.

일봉의 날짜는 거래소 현지 날짜로 표시합니다. 주말·휴장일은 생성하지 않습니다. 분봉의 조회 가능 기간은 Yahoo의 제공 제한을 따르므로 오래된 분봉 요청에 실패하면 최근의 짧은 기간으로 요청하세요.

## 자동 업데이트

- `StartInvestment.cmd` 또는 `python launch_app.py`로 **앱을 실행할 때마다** GitHub 최신 커밋을 확인합니다. 실행 중인 창은 강제로 재시작하지 않습니다.
- 새 버전이 있으면 앱 폴더의 `.investment-app` 아래에 별도 실행 환경을 설치하고 기본 동작에 필요한 모듈을 검사한 뒤 새 버전으로 실행합니다. 업데이트가 없는 경우 재설치하지 않습니다.
- 다운로드·설치·업데이트 확인에 실패하면 마지막으로 설치가 완료된 버전으로 실행합니다. 처음 실행할 때는 설치를 위한 인터넷 연결이 필요합니다. 주가 조회에는 별도로 Yahoo/KRX 연결이 필요합니다.
- 현재 버전과 직전 버전만 보관합니다. `data` 폴더와 기존 CSV는 업데이트나 이전 버전 정리 대상에 포함하지 않습니다. 한 폴더에서 앱은 하나만 실행합니다.
- 제목 영역에 앱 버전과 Git 커밋 앞 8자리를 표시합니다. 런처는 `launch_app.py`와 `StartInvestment.cmd` 두 파일이며, 앱 코드와 패키지 설치는 자동으로 관리합니다.
- 업데이트 확인을 생략하고 설치된 버전을 실행하려면 `python launch_app.py --no-update`를 사용합니다.

macOS/Linux에서는 Tcl/Tk가 포함된 Python으로 `python launch_app.py`를 실행할 수 있습니다. Windows를 기본 사용 환경으로 검증합니다.

## Python API / 명령줄 기능

Yahoo Finance의 주가 이력을 받아 **시간순 pandas DataFrame, CSV, SQLite**로 저장합니다. API 키 없이 종목 티커, 기간, 봉 간격을 지정할 수 있습니다. 기본 조회는 최근 1년의 일봉입니다.

- 미국 주식과 Yahoo에 등록된 한국 주식 조회
- 시가·고가·저가·종가·수정종가·거래량, 배당·분할 이벤트
- UTC 시각과 거래소 현지 날짜를 함께 보존
- CSV마다 조회 조건·통화·시간대·수집 시각을 JSON으로 기록
- SQLite 재수집 시 중복 없이 갱신
- 입력 오류, 빈 데이터, 네트워크 오류 처리와 제한된 재시도

### 명령줄 도구 설치

Python 3.10 이상이 필요합니다.

```bash
git clone https://github.com/SKKUPhysicsKing/Investment.git
cd Investment
python -m venv .venv
```

Windows PowerShell에서는 활성화 없이 가상환경의 Python으로 설치할 수 있습니다.

```powershell
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m investment --help
```

macOS/Linux에서는 `source .venv/bin/activate`를 실행한 뒤:

```bash
python -m pip install -e .
```

직접 GUI를 설치해서 개발하려면 `python -m pip install -e ".[gui]"` 후 `python -m investment gui`로 실행합니다. 이 직접 실행 방식에는 런처의 자동 업데이트가 적용되지 않습니다.

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
python -m pip install -e ".[gui,dev]"
ruff check .
ruff format --check .
pytest -q
python -m build
```

테스트는 네트워크 없이 날짜 경계, 한국/미국 시간대, DST, 중복·결측 처리, 회사 검색, 내보내기, SQLite 갱신, 업데이트 전환·실패 시 복구를 검증합니다. GUI 통합 테스트는 검색→조회→그래프→CSV 저장과 최소 창 크기에서 주요 컨트롤이 화면 안에 들어오는지를 확인합니다. Linux에서는 `xvfb-run -a pytest -q`로 GUI 테스트를 실행합니다. 디스플레이가 없는 일반 터미널에서는 GUI 테스트만 건너뜁니다.

GitHub Actions는 Linux Python 3.10/3.12/3.13과 Windows Python 3.12에서 검증과 패키지 빌드를 실행합니다. 실제 Yahoo/KRX 연결은 앱 또는 위 명령줄 예제로 별도 확인할 수 있습니다.

## 데이터 출처

이 프로젝트는 [yfinance](https://ranaroussi.github.io/yfinance/)를 통해 Yahoo Finance 데이터를 요청합니다. yfinance는 Yahoo의 공식 SDK가 아니며, 가용성과 요청 제한은 서비스 상황에 따라 달라집니다. 다운로드한 데이터는 저장소에 커밋하지 않습니다. 데이터 이용 범위는 [Yahoo 이용 약관](https://legal.yahoo.com/us/en/yahoo/terms/otos/index.html)을 확인하세요.

- [yfinance history API와 날짜·조정 옵션](https://ranaroussi.github.io/yfinance/reference/yfinance.price_history.html)
- [Yahoo Finance 종목 검색](https://finance.yahoo.com/)
- [KRX KIND 상장법인 목록](https://kind.krx.co.kr/corpgeneral/corpList.do?method=loadInitPage)
