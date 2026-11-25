# Investment — 주가·뉴스 시계열 앱

**회사명 검색 → 기간 입력 → 주가 그래프·뉴스/공시 시계열 → CSV 내보내기**를 제공하는 Windows 데스크톱 앱입니다. **바탕화면 아이콘으로 콘솔 없이 실행**하며, GitHub에서 검증된 최신 앱을 자동으로 확인합니다. 기존 Python API와 명령줄 수집 기능도 사용할 수 있습니다.

## Windows에서 앱 실행

**Windows 10/11 x64용 앱에는 Python과 필요한 패키지가 포함되어 있습니다. Python 설치, CMD, PowerShell, 가상환경 활성화가 필요하지 않습니다.**

1. [Investment.exe 다운로드](https://github.com/SKKUPhysicsKing/Investment/releases/latest/download/Investment.exe)
2. 기존에 사용하던 **`Investment` 폴더**에 저장합니다. 처음 사용하는 경우 원하는 앱 폴더에 저장합니다.
3. **`Investment.exe`를 더블클릭**합니다. 준비/업데이트 상태는 작은 앱 창으로 표시하며 CMD 창은 열리지 않습니다.
4. 첫 실행이 완료되면 **바탕화면과 시작 메뉴의 `Investment` 아이콘**이 생깁니다. 다음부터는 그 아이콘을 더블클릭하면 됩니다.

CSV와 뉴스 DB는 계속 **처음 실행한 앱 폴더의 `data`**에 저장합니다. 기존 `data` 폴더를 옮기거나 삭제할 필요가 없습니다. 앱과 업데이트 파일은 사용자 전용 경로에 보관하므로 관리자 권한을 요구하지 않습니다. 첫 실행 시 포함된 런타임을 준비하므로 앱 창이 나타나기까지 잠시 걸릴 수 있습니다.

### 아이콘 앱의 자동 업데이트

- 아이콘으로 실행할 때 GitHub의 최신 **Windows 배포판**을 확인합니다. 소스의 `main` 변경은 자동 검사와 Windows 앱 빌드·실행 검증이 완료된 뒤 배포됩니다.
- 새 앱을 `%LOCALAPPDATA%\Investment\desktop` 아래에 다운로드하고 파일 크기·SHA-256을 검증합니다. 새 앱의 GUI가 정상 초기화된 다음 활성 버전과 아이콘을 갱신합니다.
- 다운로드나 검증에 실패하면 설치된 앱을 계속 실행합니다. **업데이트 건너뛰고 실행** 버튼으로 현재 앱을 열 수도 있습니다. 실행 중인 앱을 강제로 재시작하지 않습니다.
- 마지막으로 정상 실행된 버전과 그 직전 버전을 보관합니다. 새 버전의 시작이 실패하면 재시도를 잠시 유예하고 이전 앱을 사용합니다. CSV와 뉴스 DB는 버전 정리 대상에 포함하지 않습니다.
- 문제가 생기면 콘솔 대신 오류 창을 표시합니다. 시작 기록은 사용자 전용 앱 경로의 `startup.log`에 남깁니다.

### 개발자용 소스 실행

소스를 직접 실행하려면 Python 3.10 이상(Tcl/Tk 포함)이 필요합니다. 아래 기존 런처 방식도 계속 지원하며 이 방식에는 CMD 창이 표시됩니다.

1. [최신 프로젝트 ZIP 다운로드](https://github.com/SKKUPhysicsKing/Investment/archive/refs/heads/main.zip)
2. ZIP을 원하는 앱 폴더에 **압축 해제**합니다.
3. 그 폴더의 **`StartInvestment.cmd`를 더블클릭**합니다.
4. 첫 실행은 필요한 패키지를 설치하므로 몇 분 걸릴 수 있습니다. 준비가 끝나면 앱 창이 열립니다.

Git 설치, 가상환경 활성화, PowerShell 실행 정책 변경, Yahoo 로그인은 필요하지 않습니다. 주가와 기본 뉴스 출처는 API 키 없이 사용하며, 추가 뉴스/공시 API는 선택적으로 설정합니다. ZIP 안에서 바로 실행하지 말고 먼저 압축을 해제하세요.

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
5. **주가 CSV**를 누르면 **앱 실행 폴더의 `data` 폴더**에 조회한 전체 데이터를 저장합니다. 저장 전에는 CSV를 만들지 않습니다. **data 폴더 열기**로 저장한 파일을 확인합니다.

예: `Investment/StartInvestment.cmd`로 실행하면 `Investment/data/005930.KS_2026-01-02_2026-11-25_1d.csv`와 같은 이름으로 저장합니다. 날짜는 실제 반환된 첫/마지막 봉 기준이며 같은 파일명이 있으면 `_2`, `_3`을 붙여 기존 파일을 보존합니다. 기존 CLI와 같은 11개 열 및 JSON 메타데이터를 저장합니다. 그래프의 종가/수정종가 선택과 관계없이 CSV에는 두 열을 모두 담습니다.

검색어·날짜를 바꿔도 새로 조회하기 전에는 기존 그래프가 유지됩니다. 내보내기는 **현재 표시 중인 데이터**를 기준으로 하며 회사명·실제 데이터 범위·봉 수를 그래프 위에 표시합니다. 조회 중에도 창이 응답하며, 실패하면 기존 그래프를 보존하고 오류를 안내합니다.

일봉의 날짜는 거래소 현지 날짜로 표시합니다. 주말·휴장일은 생성하지 않습니다. 분봉의 조회 가능 기간은 Yahoo의 제공 제한을 따르므로 오래된 분봉 요청에 실패하면 최근의 짧은 기간으로 요청하세요.

### 주가와 뉴스·공시를 한 화면에서 보기 (v0.5.0)

**주가 그래프**에는 위에서부터 **주가 → 거래량 → 뉴스/공시 타임라인**을 표시합니다. 세 영역은 동일한 X축을 공유하므로 확대·이동할 때 날짜가 함께 움직입니다.

1. 회사와 기간을 선택해 **조회 · PLOT**을 누릅니다. `data/news.sqlite`에 저장된 같은 회사·기간의 자료가 있으면 타임라인에 자동으로 불러옵니다.
2. 그래프 아래 **그래프 뉴스 수집**을 누르면 **현재 그려진 회사·기간**의 뉴스와 공시를 가져와 즉시 같은 그래프에 표시합니다. 왼쪽의 다음 검색 조건을 수정해도 표시 중인 그래프의 종목과 섞지 않습니다.
3. **실적·공시·뉴스** 세 행의 마커가 해당 날짜/시각에 표시됩니다. 일봉·주봉·월봉에서는 같은 날짜·유형을 묶고 건수를 표시합니다. 시각을 제공하는 분봉 자료는 거래소 현지 시각에 놓으며, 날짜만 있는 자료는 `시각 미상`의 하루 구간으로 표시합니다.
4. 마커 위에 마우스를 올리면 제목을 확인할 수 있습니다. 클릭하면 **그래프를 유지한 채 아래 목록에 해당 묶음의 기사를 시간순으로 표시**합니다. 목록 항목을 선택하면 주가와 거래량에도 같은 위치의 가이드가 나타납니다.
5. **기사 상세**는 그래프와 함께 볼 수 있는 별도 창으로 요약·본문·출처·시각 기준을 표시합니다. **원문**은 브라우저에서 기사를 엽니다. `전체/실적/공시/뉴스` 필터와 **전체 목록**으로 표시 범위를 바꿀 수 있습니다.

기사 목록은 그래프의 현재 확대 범위를 따라가며 최대 1,000행을 표시합니다. 타임라인의 마커와 CSV에는 수집 자료를 그대로 유지합니다. 마커가 많으면 축의 제목 라벨 수만 줄이고, 확대·마우스·클릭으로 각 자료를 확인합니다. 그래프와 기사 목록 사이의 구분선을 끌어 높이를 조절할 수 있습니다.

작은 창에서는 주가와 기사 목록을 읽을 수 있도록 거래량을 자동으로 접습니다. 그래프 위 **거래량** 체크박스로 직접 켜고 끌 수 있으며, 창이나 그래프 영역을 키우면 자동으로 접혔던 거래량을 다시 표시합니다.

주말·휴장일 기사는 해당 달력 날짜에 표시합니다. 따라서 선택 기간에 금요일 주가와 일요일 기사가 함께 있으면 일요일까지 X축이 이어집니다. 마커 색과 모양은 자료 유형을 구분하며 가격 상승·하락을 의미하지 않습니다. 실제 실적 발표일과 정기보고서 제출일, 제공자 시각과 원문 발행 시각은 다를 수 있어 상세의 시각 기준을 함께 확인하세요.

## 뉴스 · 공시 시계열 (v0.3.0)

1. 왼쪽에서 회사를 선택하고 시작일·종료일을 입력합니다. **뉴스 · 공시** 탭에서 **뉴스/공시 수집**을 누릅니다. 주가를 먼저 조회하지 않아도 됩니다. 뉴스 역시 양 끝 날짜를 포함합니다.
2. 기사 목록을 날짜순으로 확인하고, 검색어·사건 유형·긍정/부정 추정으로 필터링합니다. 목록은 최근 1,000건까지 표시하고 **뉴스 CSV**는 필터와 관계없이 수집한 전체 자료를 저장합니다.
3. **선택 기사 · 내용** 탭에서 제목, 요약, 원문 링크, 공개 본문 발췌, 분류 근거, 출처별 시각을 확인합니다. **원문 열기**로 브라우저에서 읽거나 **공개 본문 추가**로 선택 기사의 공개 내용을 추가 수집할 수 있습니다.
4. **출처별 수집 상태** 탭에서 각 출처의 확보 수·요청 수·조회 제한·실패 이유를 확인합니다. 키가 없는 출처는 `설정 필요`로 표시하고 나머지 출처를 계속 수집합니다. 일부 출처의 오류나 취소가 이미 확보한 자료를 버리지 않습니다.
5. 같은 회사의 주가를 조회했다면 그래프 아래 공통 날짜 축의 타임라인에도 표시됩니다. 마커 클릭과 기사 목록 선택은 주가 그래프를 유지하며 날짜별 자료를 연결합니다. 별도의 뉴스 탭에서는 전체 출처별 상태·본문 추가 수집·수동 분류·내보내기를 사용할 수 있습니다.

### 연결한 출처와 제공 범위

| 출처 | 수집 자료 | 설정·제한 |
| --- | --- | --- |
| Google News RSS | 한국어·영어 회사명/별칭 검색, 날짜 구간별 기사 링크 | 키 불필요. 30일 단위 검색 후 결과가 100건이면 구간을 다시 분할. 하루 단위 상한과 검색 누락 가능 |
| Yahoo | 선택 종목의 최신 뉴스와 보도자료, 제공 요약 | 키 불필요. 임의의 과거 전 기간을 제공하는 뉴스 API가 아님 |
| GDELT DOC | 해외 매체 기사·원문 URL | 키 불필요. 최근 약 3개월 검색 표본. `first_seen`은 최초 관측 시각이며 발행 시각과 다름 |
| 공식 뉴스룸 RSS/IR | 회사 발표·제품·실적 보도자료와 RSS 제공 내용 | 키 불필요. 삼성전자 한국/글로벌, Apple, NVIDIA를 자동 연결. 최신 피드 범위만 제공 |
| OpenDART | 국내 선택 기업의 전체 공시 유형, 정정 공시, 접수번호 | DART 키 필요. 기업 고유번호로 조회하고 제공된 공시 목록 페이지를 순회 |
| 네이버 뉴스 검색 | 국내외 회사명/별칭 기사, 제공 요약, 원문 URL | Client ID/Secret 필요. 최신순 최대 검색 위치 1,000, 날짜 구간 검색 인자가 없어 오래된 기사는 제한 |
| SEC EDGAR | 미국 등록 기업의 정기·수시 공시와 과거 이력 파일 | API 키 불필요. 실제 연락 이메일 필요. CIK로 연결하며 제출일과 실적 발표일은 다를 수 있음 |
| Finnhub | 종목별 회사 뉴스, 요약 | API 키 필요. 계정별 과거 조회 범위·권한·호출 한도 적용, 북미 기업 중심 |
| Alpha Vantage | 종목별 기간 뉴스, 요약, 제공자 감성·관련도 | API 키와 뉴스 API 권한 필요. 유료 기능. 한국 Yahoo 티커 직접 연결 미지원 |
| 추가 RSS/Atom·BIGKinds 파일 | 사용자가 지정한 피드 및 내려받은 과거 기사 자료 | 피드 URL 추가 또는 XLSX/CSV 가져오기. 회사명/별칭과 선택 기간으로 필터링 |

각 출처는 동시에 수집하고, 결과를 제목·날짜 또는 동일 원문 URL로 중복 정리합니다. 여러 경로에서 발견한 URL·제목·출처·시각 기록은 함께 보존합니다. 공시는 접수번호를 구분하므로 정정 공시를 원래 공시와 합치지 않습니다. `API 조회 완료`는 제공된 목록의 조회 완료를 뜻하며 모든 플랫폼의 모든 기사를 확보했다는 뜻은 아닙니다.

### 자료를 더 많이 모으려면

**출처 · API 설정**에서 필요한 API 키와 SEC 연락 이메일을 입력하고, 해당 회사의 추가 별칭·IR/뉴스룸 RSS URL을 지정하세요. 별칭은 쉼표, RSS URL은 줄바꿈으로 구분합니다. 추가 RSS는 회사명/별칭이 제목 또는 요약에 포함된 항목을 수집하며, 자동 연결한 공식 회사 피드는 제품명만 있는 발표도 포함합니다.

기본 한도는 **출처별 60회 요청·10,000건**, 공개 본문 추가 수집 10건입니다. 요청 한도는 출처별 최대 300회·50,000건, 본문은 최대 50건으로 조정할 수 있습니다. 한도에 도달하면 `일부 수집`으로 표시합니다. 긴 기간을 여러 구간으로 나눠 재수집하면 기존 저장 자료와 합쳐집니다. 실패한 출처만 켜서 다시 시도할 수도 있습니다. 취소 후에는 진행 중인 네트워크 요청이 끝나는 대로 확보한 결과를 표시합니다.

**키는 앱 설정 파일·SQLite·CSV·로그에 저장하지 않고 현재 실행에서만 사용**합니다. 다음 환경변수를 설정해 실행할 수도 있습니다.

| 환경변수 | 용도 |
| --- | --- |
| `DART_API_KEY` | OpenDART 인증키 |
| `NAVER_CLIENT_ID`, `NAVER_CLIENT_SECRET` | 네이버 검색 API 인증 |
| `FINNHUB_API_KEY` | Finnhub 인증키 |
| `ALPHAVANTAGE_API_KEY` | Alpha Vantage 인증키 |
| `SEC_CONTACT` | SEC 요청 식별용 실제 연락 이메일 |

과거 한국 기사 자료가 중요하면 BIGKinds에서 회사·기간을 검색해 XLSX/CSV로 내려받은 뒤 **BIGKinds/파일 가져오기**를 사용하세요. `일자`/`날짜`/`date`와 `제목`/`title` 열이 필요하고, `언론사`, `URL`, `본문`, `키워드`가 있으면 함께 활용합니다. CSV는 UTF-8 또는 CP949를 지원합니다. BIGKinds의 로그인·다운로드를 자동화하는 기능은 포함하지 않습니다.

### 저장·시각·분류 해석

- 뉴스는 **현재 앱 폴더의 `data/news.sqlite`에 자동 누적**합니다. **저장 자료**는 선택 회사/기간의 기존 자료를 인터넷 조회 없이 읽습니다. 재수집해도 이전 기사·공개 본문·수동 논조 분류를 보존합니다.
- **뉴스 CSV**는 `data/005930.KS_news_2026-11-01_2026-11-25.csv`와 같은 UTF-8 BOM 파일과 `.metadata.json`을 만듭니다. 동일 이름은 `_2` 등을 붙여 보존합니다. 메타데이터에 요청 기간·거래소 시간대·출처별 상태·제한을 기록합니다.
- CSV에는 제목, 원문 URL, 요약, 공개 본문 발췌, 사건 분류, 논조 추정·근거·방법, 제공자 감성, UTC 시각, 거래소 현지 날짜, 시각 정밀도·기준, 수집 시각과 출처별 관측 기록이 포함됩니다. 리스트 필드는 JSON 문자열입니다.
- 날짜만 제공되는 DART 공시·가져온 자료에 발표 시각을 만들어 넣지 않습니다. 해당 행의 `published_at`/`timestamp`는 비워 두고 `time_precision=day`로 기록합니다. `event_date`를 날짜별 분석에 사용하세요. 원문에서 확인한 발행·수정 시각은 별도 열로 보존합니다.
- 긍정/부정은 제목·제공 요약의 제한된 **키워드 규칙**입니다. 실적 개선·실적 쇼크 같은 표현을 분류하며, 근거가 없으면 판단을 유보합니다. 점수는 정확도나 주가 상승/하락 확률이 아닙니다. **분류 수정**으로 논조와 근거를 직접 기록할 수 있습니다. 제공자 감성 점수는 앱의 규칙 분류와 별도로 보존합니다.
- 기사 발행·수정·수집 시각은 서로 다릅니다. 과거 시점 분석 시 그 시점에 실제 공개되어 있던 정보인지 따로 확인해야 하며, 차트에 함께 표시된 것만으로 주가 변동의 원인이라고 볼 수 없습니다.
- 본문은 공개 RSS 제공 내용 또는 접근 가능한 HTML/PDF의 **발췌**입니다. PDF는 앞 15페이지, 추가 본문은 최대 40,000자로 제한합니다. robots.txt와 요청 간격을 확인하고 유료벽·로그인·접근 차단은 우회하지 않습니다. Google RSS는 기사 링크 중심으로 보존합니다. 본문 수집 실패는 기사 메타데이터와 구분해 기록합니다.

개발용 Python에서도 `investment.news_collect.collect_news`, `NewsQuery`, `NewsSettings`를 사용할 수 있습니다. 뉴스 모듈을 사용하려면 `.[gui]` 의존성을 설치하세요. 뉴스 CLI 하위 명령은 제공하지 않습니다.

## 소스 런처의 자동 업데이트

- `StartInvestment.cmd` 또는 `python launch_app.py`로 **앱을 실행할 때마다** GitHub 최신 커밋을 확인합니다. 실행 중인 창은 강제로 재시작하지 않습니다.
- 새 버전이 있으면 별도 실행 환경에 설치하고 기본 동작에 필요한 모듈을 검사한 뒤 새 버전으로 실행합니다. Windows는 경로 길이 제한을 피하기 위해 `%LOCALAPPDATA%\Investment` 아래의 짧은 전용 경로를 사용합니다. 앱 폴더와 Python 버전별로 환경을 구분하며, ZIP을 여러 단계 폴더에 풀어도 패키지 설치 경로는 길어지지 않습니다. macOS/Linux는 앱 폴더의 `.investment-app` 아래에 설치합니다. 업데이트가 없는 경우 재설치하지 않습니다.
- 다운로드·설치·업데이트 확인에 실패하면 마지막으로 설치가 완료된 버전으로 실행합니다. 처음 실행할 때는 설치를 위한 인터넷 연결이 필요합니다. 주가 조회에는 별도로 Yahoo/KRX 연결이 필요합니다.
- 현재 버전과 직전 버전만 보관합니다. `data` 폴더와 기존 CSV는 업데이트나 이전 버전 정리 대상에 포함하지 않습니다. 한 폴더에서 앱은 하나만 실행합니다.
- 제목 영역에 앱 버전과 Git 커밋 앞 8자리를 표시합니다. 런처는 `launch_app.py`와 `StartInvestment.cmd` 두 파일이며, 앱 코드와 패키지 설치는 자동으로 관리합니다.
- 업데이트 확인을 생략하고 설치된 버전을 실행하려면 `python launch_app.py --no-update`를 사용합니다.

### Windows 설치 중 `lxml` / 긴 경로 오류가 발생한 경우

초기 런처는 앱 폴더 아래에 실행 환경을 만들었기 때문에 `Investment-main` 등의 폴더가 중첩되면 Windows의 260자 경로 제한을 넘을 수 있었습니다. 수정된 런처는 짧은 사용자 전용 경로에 설치하므로 Windows 설정을 변경할 필요가 없습니다. CSV 저장 위치는 계속 **실행한 앱 폴더의 `data`**입니다.

기존 런처의 설치 오류는 앱 자동 업데이트 전에 발생하므로, `StartInvestment.cmd`가 있는 폴더에서 PowerShell을 열고 `launch_app.py`를 한 번 교체하세요.

```powershell
Invoke-WebRequest "https://raw.githubusercontent.com/SKKUPhysicsKing/Investment/main/launch_app.py" -OutFile ".\launch_app.py"
.\StartInvestment.cmd
```

앱 폴더나 `data`를 이동·삭제할 필요는 없습니다. 이전 경로에 정상 설치된 버전이 있다면 새 경로 설치에 실패하거나 오프라인으로 실행할 때 그 버전을 계속 사용할 수 있습니다. 가상환경을 직접 이동하지는 않습니다.

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

테스트는 네트워크 없이 날짜 경계, 한국/미국 시간대, DST, 중복·결측 처리, 회사 검색, 내보내기, SQLite 갱신, 업데이트 전환·실패 시 복구를 검증합니다. 뉴스는 출처별 응답 변환, API 키 미설정·오류 격리, 취소·부분 결과 보존, 과거 파일 가져오기, 중복 병합·수동 분류 보존, 날짜만 있는 공시, 본문 접근 제한을 검사합니다. GUI 통합 테스트는 검색→조회→그래프→CSV 저장, 뉴스 수집→차트 날짜 선택→전체 내보내기와 최소 창 크기의 주요 컨트롤 배치를 확인합니다. Linux에서는 `xvfb-run -a pytest -q`로 GUI 테스트를 실행합니다. 디스플레이가 없는 일반 터미널에서는 GUI 테스트만 건너뜁니다.

GitHub Actions는 Linux Python 3.10/3.12/3.13과 Windows Python 3.10/3.12에서 검증과 패키지 빌드를 실행합니다. Windows에서는 깊게 중첩된 앱 폴더로부터 실제 가상환경·패키지를 설치하고, 문제의 `lxml` 리소스 파일 생성, 재실행 시 설치 생략, 기존 CSV 보존을 추가 검증합니다. 이 설치 테스트의 GitHub 응답만 체크아웃한 소스로 대체합니다. 실제 Yahoo/KRX 연결은 앱 또는 위 명령줄 예제로 별도 확인할 수 있습니다.

Windows 앱은 모든 검사가 통과한 `main`에서 Python 3.12와 PyInstaller로 빌드합니다. 실제 `Investment.exe`의 PE 헤더가 Windows GUI 형식인지, 콘솔 창 없이 포함된 Python/Tk로 주가·뉴스 UI가 열리는지, 바탕화면/시작 메뉴 바로가기 설정, 설치 경로에서의 재실행과 기존 CSV 보존을 검증한 뒤 GitHub Releases에 EXE와 SHA-256을 게시합니다. 배포 파일에는 별도의 Python 설치가 필요하지 않습니다.

Windows에서 직접 빌드하려면:

```powershell
python -m pip install -e ".[gui,desktop-build]"
python scripts/build_windows.py
python tests/windows_desktop_smoke.py dist/Investment.exe
```

## 데이터 출처

이 프로젝트는 [yfinance](https://ranaroussi.github.io/yfinance/)를 통해 Yahoo Finance 데이터를 요청합니다. yfinance는 Yahoo의 공식 SDK가 아니며, 가용성과 요청 제한은 서비스 상황에 따라 달라집니다. 다운로드한 데이터는 저장소에 커밋하지 않습니다. 데이터 이용 범위는 [Yahoo 이용 약관](https://legal.yahoo.com/us/en/yahoo/terms/otos/index.html)을 확인하세요.

- [yfinance history API와 날짜·조정 옵션](https://ranaroussi.github.io/yfinance/reference/yfinance.price_history.html)
- [Yahoo Finance 종목 검색](https://finance.yahoo.com/)
- [KRX KIND 상장법인 목록](https://kind.krx.co.kr/corpgeneral/corpList.do?method=loadInitPage)
- [OpenDART 공시검색 API](https://opendart.fss.or.kr/guide/detail.do?apiGrpCd=DS001&apiId=2019001)
- [네이버 뉴스 검색 API](https://developers.naver.com/docs/serviceapi/search/news/news.md)
- [SEC EDGAR API·접근 지침](https://www.sec.gov/search-filings/edgar-application-programming-interfaces)
- [GDELT DOC API](https://blog.gdeltproject.org/gdelt-doc-2-0-api-debuts/)
- [Finnhub Company News](https://finnhub.io/docs/api/company-news)
- [Alpha Vantage News & Sentiment](https://www.alphavantage.co/documentation/#news-sentiment)
- [BIGKinds](https://www.bigkinds.or.kr/)
