# OCR 및 데이터 크롤링 통합 프로젝트

본 프로젝트는 물류 계근표 OCR 파싱 엔진과 누리장터 데이터 수집 시스템을 통합한 솔루션입니다. 관심사 분리(SoC) 원칙을 적용하여 계층화된 아키텍처로 설계되었습니다.

## 목차
- [프로젝트 구조](#프로젝트-구조)
- [실행 방법](#실행-방법)
- [설계 및 주요 기능](#설계-및-주요-기능)
- [테스트 및 검증](#테스트-및-검증)
- [결과 산출물](#결과-산출물)
- [한계점 및 개선 아이디어](#한계점-및-개선-아이디어)

---

## 프로젝트 구조

```
.
├── crawler/                # 누리장터 크롤링 패키지
│   ├── client.py           # API 통신 및 재시도 로직 (지수 백오프 적용)
│   ├── transformer.py      # 데이터 정규화 및 DTO 변환
│   ├── storage.py          # SQLite 기반 원자적 트랜잭션 관리
│   └── crawler.py          # 크롤링 워크플로우 제어 (Orchestrator)
├── ocr_parser/             # OCR 파싱 패키지
│   ├── schemas.py          # Pydantic 기반 데이터 무결성 검증
│   └── processor.py        # 차량번호 특화 정규식 및 파싱 엔진
├── tests/                  # 검증 체계
│   ├── test_parser.py      # OCR 유닛 테스트 (4개 샘플 케이스)
│   ├── test_crawler_unit.py # 크롤러 모듈별 단위 테스트 (Mock 활용)
│   └── test_crawler_integrated.py # 실제 API 연동 통합 테스트
├── samples/                # OCR 샘플 데이터
│   ├── sample_01.json      # 계근표 샘플 1
│   ├── sample_02.json      # 계근표 샘플 2
│   ├── sample_03.json      # 계근표 샘플 3
│   └── sample_04.json      # 계근표 샘플 4
├── data/                   # SQLite DB 및 상태 저장소 (자동 생성)
│   └── crawler_state.db    # 크롤링 상태 및 증분 수집 관리
├── output/                 # 결과물 저장소 (자동 생성)
│   ├── ocr_results.csv     # OCR 파싱 결과
│   ├── nuri_notices.json   # 누리장터 수집 결과 (JSON)
│   └── nuri_notices.csv    # 누리장터 수집 결과 (CSV)
├── main.py                 # 통합 실행 컨트롤러 (CLI)
├── requirements.txt        # 의존성 관리
├── README.md               # 본 문서
└── DESIGN.md               # 아키텍처 설계 문서
```

---

## 실행 방법

### 환경 설치

**필수 요구사항**
- Python 3.9 이상 (개발 환경: Python 3.14.0)
- OS: macOS / Linux / Windows 모두 호환

**패키지 설치**
```bash
# 가상환경 생성 (권장)
python3 -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# 의존성 설치
pip install -r requirements.txt
```

**주요 패키지 버전**
```
pydantic>=2.0.0           # 데이터 검증
loguru>=0.7.0             # 구조화된 로깅
requests>=2.31.0          # HTTP 통신
beautifulsoup4>=4.12.0    # HTML 파싱
pytest>=7.4.0             # 테스트 프레임워크
pytest-asyncio>=0.21.0    # 비동기 테스트
```

### 프로그램 실행

**통합 CLI 인터페이스**

```bash
# 도움말 확인
python main.py --help

# 사용 예시:
#   python main.py ocr                           # OCR만 실행
#   python main.py crawler --pages 3             # 크롤러만 실행 (3페이지)
#   python main.py crawler --pages 5 --details   # 상세정보 포함
#   python main.py crawler --mode interval --seconds 3600 --pages 2  # 1시간 간격 반복 실행
#   python main.py all --pages 2                 # 둘 다 실행
```

**과제 A: OCR 파싱 실행**
```bash
# samples/ 폴더의 모든 JSON 파일 파싱
python main.py ocr

# 실행 결과 예시:
# ============================================================
# 과제 A: OCR 계근표 파싱 시작
# ============================================================
# [1] sample_01.json 파싱 성공: 8713
# [2] sample_02.json 파싱 성공: 80구8713
# [3] sample_03.json 파싱 성공: 5405
# [4] sample_04.json 파싱 성공: 0580
# 결과 저장 완료: output/ocr_results.csv
# ============================================================
```

**과제 B: 크롤링 실행**

**1회성 실행 모드 (기본값, Cron/스케줄러 연동용)**
```bash
# 1페이지 수집
python main.py crawler --pages 1

# 3페이지 수집 + 상세 정보 포함
python main.py crawler --pages 3 --details
```

**반복 실행 모드 (내장 스케줄러)**
```bash
# 1시간(3600초)마다 자동으로 3페이지 수집
python main.py crawler --mode interval --seconds 3600 --pages 3

# 30분마다 상세정보 포함하여 수집
python main.py crawler --mode interval --seconds 1800 --pages 5 --details
```

**실행 결과 로그 예시:**
```
============================================================
과제 B: 누리장터 데이터 수집 시작 (모드: once)
설정 정보: 최대 3페이지, 상세조회: True
============================================================

[작업 시작] 페이지 1/3
페이지 1: 10건의 공고 발견
[1/10] 상세정보 보강 완료: R26BK01321500
[1/10] DB 저장 완료: R26BK01321500
...
============================================================
누리장터 데이터 수집 완료 리포트
------------------------------------------------------------
처리 페이지: 3개 (실패: 0개)
발견 공고: 30건
신규 수집: 30건
중복 제외: 0건
검증 에러: 0건
수집 성공률: 100.0%
============================================================
데이터 내보내기 성공 (CSV): output/nuri_notices.csv
수집 완료: 총 30건
```

**둘 다 실행**
```bash
python main.py all --pages 2
```

### CLI 파라미터 상세

| 파라미터 | 필수 여부 | 기본값 | 설명 |
|---------|---------|--------|------|
| `task` | 필수 | - | 실행할 작업: `ocr`, `crawler`, `all` |
| `--mode` | 선택 | `once` | 크롤러 실행 모드: `once` (1회 실행), `interval` (반복 실행) |
| `--seconds` | 선택 | `3600` | `interval` 모드 시 대기 시간 (초 단위) |
| `--pages` | 선택 | `1` | 크롤링할 페이지 수 |
| `--details` | 선택 | `False` | 상세정보 수집 활성화 플래그 |

### 생성되는 파일

```bash
samples/
├── sample_01.json ~ sample_04.json  # 기존 샘플 데이터
└── (없을 경우 자동 생성됨)

data/
└── crawler_state.db        # 수집 이력 및 중복 체크용 DB (자동 생성)

output/
├── ocr_results.csv         # OCR 파싱 결과 (UTF-8 BOM)
├── nuri_notices.json       # 누리장터 수집 결과 (JSON)
└── nuri_notices.csv        # 누리장터 수집 결과 (CSV, UTF-8 BOM)

logs/                       # (자동 생성, 필요 시)
```

---

## 설계 및 주요 기능

### 과제 A: OCR 파싱 엔진

**핵심 설계 원칙**
1. **노이즈 허용 파싱**: OCR 특성상 발생하는 띄어쓰기, 오탈자, 순서 변경에 강건하게 대응
2. **정규식 기반 추출**: 차량번호, 중량 패턴 매칭
3. **다단계 보정 및 검증**: 중량값 자동 보정 후 산술 관계 검증

**데이터 정규화 프로세스**

| 단계 | 입력 예시 | 처리 로직 | 출력 예시 | 구현 위치 |
|------|----------|----------|----------|----------|
| 1. 전처리 | `11시 30분`, `02:30` | 시간 패턴 제거 | (텍스트 정제) | `_clean_text()` |
| 2. 원본 추출 | `80구 8713` | 공백 제거 | `80구8713` | `parse()` |
| 3. 중량 파싱 | `14 080 kg` | 숫자 통합 + 단위 처리 | `14080` | `_extract_weight()` |
| 4. 노이즈 필터링 | `02, 11, 12080` | 100 ≤ weight ≤ 999,999 | `12080` (유효) | `_extract_weight()` |
| 5. 자동 보정 | `총12480, 공7470, 실5010` | 크기순 정렬 또는 계산 | 올바른 배치 | `parse()` |
| 6. 산술 검증 | 총-공차=실중량 | 오차 ±10kg 허용 | `is_weight_valid: True` | `WeightTicket` validator |

**중량값 자동 보정 로직 (핵심 엔지니어링)**

OCR 오인식으로 인해 총중량, 공차중량, 실중량이 뒤섞여 추출될 수 있습니다. 이를 자동으로 보정하는 로직:

```python
# 1. 세 값이 모두 추출된 경우: 크기 순서대로 자동 배치
if len(non_zero) >= 3:
    all_w = sorted(non_zero, reverse=True)
    extracted['gross_weight'], extracted['tare_weight'], extracted['net_weight'] = all_w[0], all_w[1], all_w[2]

# 2. 두 값만 추출된 경우: 나머지 하나를 산술 관계로 계산
elif len(non_zero) == 2:
    if extracted['gross_weight'] > 0 and extracted['net_weight'] > 0:
        extracted['tare_weight'] = extracted['gross_weight'] - extracted['net_weight']
    elif extracted['gross_weight'] > 0 and extracted['tare_weight'] > 0:
        extracted['net_weight'] = extracted['gross_weight'] - extracted['tare_weight']
    elif extracted['tare_weight'] > 0 and extracted['net_weight'] > 0:
        extracted['gross_weight'] = extracted['tare_weight'] + extracted['net_weight']
```

**실제 처리 결과**

| 파일명 | 차량번호 | 총중량(kg) | 공차(kg) | 실중량(kg) | 검증 |
|--------|---------|-----------|---------|-----------|------|
| sample_01.json | 8713 | 12,480 | 7,470 | 5,010 | ✓ Pass |
| sample_02.json | 80구8713 | 13,460 | 7,560 | 5,900 | ✓ Pass |
| sample_03.json | 5405 | 14,080 | 13,950 | 130 | ✓ Pass |
| sample_04.json | 0580 | 14,230 | 12,910 | 1,320 | ✓ Pass |

### 과제 B: 크롤링 시스템

**계층화 아키텍처 (4-Layer)**

```
┌─────────────────────────────────────────┐
│  Orchestrator (crawler.py)              │  ← 워크플로우 제어
│  - 페이지 순회 / 재시도 전략            │
│  - 통계 수집 / 리포팅                    │
│  - 세션 관리                             │
└──────────────┬──────────────────────────┘
               │
┌──────────────┴──────────────────────────┐
│  Business Logic (transformer.py)        │  ← 데이터 정규화
│  - DTO 변환 / 검증                       │
│  - 상세 정보 병합                        │
└──────────────┬──────────────────────────┘
               │
┌──────────────┴──────────────────────────┐
│  Infrastructure (client.py, storage.py) │  ← 외부 의존성
│  - HTTP 통신 / 지수 백오프               │
│  - SQLite 트랜잭션 / 중복 체크           │
│  - 세션 로그 관리                        │
└─────────────────────────────────────────┘
```

**시스템 견고성 설계**

1. **네트워크 복원력**: 지수 백오프 (2초 → 4초 → 8초, 최대 10초 제한)
2. **데이터 원자성**: SQLite 트랜잭션으로 공고 저장과 로그 기록을 동시 수행
3. **증분 수집**: `scrap_log` 테이블을 통한 중복 데이터 자동 스킵
4. **세션 추적**: `crawl_sessions` 테이블로 작업 단위 통계 기록
5. **리소스 관리**: Context Manager 패턴으로 자동 정리

**네트워크 재시도 전략 상세**

```python
# Rate Limit (429) 대응
if response.status_code == 429:
    retry_after = int(response.headers.get('Retry-After', 60))
    # 서버 지시를 준수하여 대기

# 서버 에러 (5xx) 대응
if 500 <= response.status_code < 600:
    wait_time = min(2 ** attempt, 10)  # 지수 백오프 (최대 10초)

# 클라이언트 에러 (4xx) 대응
if 400 <= response.status_code < 500:
    # 즉시 중단 (재시도 무의미)
    raise NonRetryableAPIError()
```

**데이터베이스 트랜잭션 관리**

공고 데이터와 수집 로그를 하나의 트랜잭션으로 처리하여 데이터 무결성 보장:

```python
# storage.py::save_notice()
try:
    with self.conn:  # 트랜잭션 시작
        # 1. 공고 데이터 저장
        self.conn.execute("INSERT OR REPLACE INTO nuri_notices ...")
        
        # 2. 성공 로그 기록
        self.conn.execute("INSERT OR REPLACE INTO scrap_log ...")
        
        # COMMIT (자동)
except Exception as e:
    # ROLLBACK (자동) - 데이터 저장은 성공했는데 로그가 안 남는 불일치 방지
    self.log_error(notice_id, str(e))
```

**코드 품질 원칙**

| 원칙 | 구현 방법 | 파일 |
|------|----------|------|
| 단일 책임 | Client는 통신만, Transformer는 변환만 | client.py, transformer.py |
| 의존성 역전 | Crawler는 추상화된 인터페이스에 의존 | crawler.py |
| 컨텍스트 관리 | `with NuriCrawler()` 자동 리소스 해제 | crawler.py |
| 데이터 검증 | Pydantic 모델을 통한 타입 및 비즈니스 규칙 검증 | schemas.py, transformer.py |

---

## 테스트 및 검증

### 테스트 실행

```bash
# 전체 테스트 실행
pytest -v

# 개별 테스트 실행
pytest tests/test_parser.py -v                # OCR 파싱
pytest tests/test_crawler_unit.py -v          # 크롤러 유닛 테스트
pytest tests/test_crawler_integrated.py -v    # 통합 테스트
```

### 테스트 커버리지

| 테스트 구분 | 테스트 케이스 | 목적 |
|------------|-------------|------|
| OCR 파싱 | 4건 | 샘플 데이터 파싱 정확도 검증 |
| 크롤러 통합 | 8건 | End-to-End 실제 API 연동 검증 |

### 주요 테스트 케이스

**OCR 파싱 테스트**
```python
test_json_samples[sample_01.json-8713-12000]
   - 차량번호 추출: 8713 ✓
   - 시간 데이터(02, 11) 필터링 ✓
   - 총중량 임계값 검증: >= 12000kg ✓
   - 산술 검증 통과 ✓

test_csv_excel_compatibility
   - UTF-8 BOM 인코딩 확인 ✓
   - 엑셀 한글 깨짐 방지 검증 ✓
```

**크롤러 통합 테스트**
```python
test_full_logic_integration_with_new_architecture
   - 실제 누리장터 API 호출 ✓
   - DB 저장 및 중복 체크 ✓
   - DTO 타입 안정성 검증 ✓

test_backward_compatibility
   - 기존 코드 호출 방식 유효성 확인 ✓

test_incremental_crawling
   - 1차 수집: 5건 저장 ✓
   - 2차 수집: 중복 자동 스킵 ✓
   - DB 건수 불변 검증 ✓

test_with_detail_fetching
   - 상세 정보 API 호출 ✓
   - raw_data 내 detail 키 보강 확인 ✓

test_export_functionality
   - JSON 파일 생성 검증 ✓
   - CSV 파일 생성 검증 ✓

test_statistics
   - 통계 지표 집계 정확성 확인 ✓
   - 필수 키 존재 여부 검증 ✓

test_context_manager_usage
   - with 문을 통한 자동 리소스 해제 ✓

test_error_resilience
   - 개별 페이지 에러 시 전체 프로세스 계속 진행 ✓
   - 장애 허용(Fault Tolerance) 검증 ✓
```

---

## 결과 산출물

### 파일 형식

**OCR 파싱 결과 (output/ocr_results.csv)**
```csv
ticket_number,vehicle_number,gross_weight,tare_weight,net_weight,parsed_at,is_weight_valid
T-2024-001,8713,12480,7470,5010,2026-02-06T10:47:44.123456,True
T-2024-002,80구8713,13460,7560,5900,2026-02-06T10:47:44.234567,True
```

**누리장터 수집 결과 (output/nuri_notices.json)**
```json
[
  {
    "notice_id": "R26BK01321500",
    "title": "전자조달 시스템 개선사업",
    "org_name": "조달청",
    "notice_type": "용역",
    "bid_method": "일반경쟁입찰",
    "due_date": "2026-02-15",
    "announce_date": "2026-02-05",
    "budget": "150000000",
    "demand_company": "조달청",
    "detail_url": "https://nuri.g2b.go.kr/nn/nnb/nnbb/selectBidNoceDetl.do?pbancNo=R26BK01321500",
    "created_at": "2026-02-06T10:47:06"
  }
]
```

**파일 특징**
- CSV는 UTF-8 BOM 인코딩 (엑셀에서 한글 깨짐 방지)
- JSON은 `ensure_ascii=False` 옵션으로 한글 가독성 확보
- 모든 타임스탬프는 ISO 8601 형식

### 데이터베이스 스키마

**테이블: nuri_notices**
```sql
CREATE TABLE nuri_notices (
    notice_id TEXT PRIMARY KEY,        -- 입찰공고번호
    title TEXT NOT NULL,               -- 공고명
    org_name TEXT,                     -- 공고기관
    notice_type TEXT,                  -- 공고유형
    bid_method TEXT,                   -- 입찰방식
    due_date TEXT,                     -- 마감일
    announce_date TEXT,                -- 게시일
    budget TEXT,                       -- 배정예산
    demand_company TEXT,               -- 수요기관
    detail_url TEXT,                   -- 상세페이지 URL
    raw_data TEXT,                     -- API 응답 전문 (JSON)
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

**테이블: scrap_log** (증분 수집 체크포인트)
```sql
CREATE TABLE scrap_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    notice_id TEXT NOT NULL UNIQUE,    -- 공고번호
    status TEXT NOT NULL,              -- SUCCESS / FAILED
    error_msg TEXT,                    -- 실패 시 에러 메시지
    collected_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

**테이블: crawl_sessions** (작업 단위 통계)
```sql
CREATE TABLE crawl_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at DATETIME,               -- 작업 시작 시각
    finished_at DATETIME,              -- 작업 종료 시각
    total_found INTEGER DEFAULT 0,     -- 발견된 총 공고 수
    total_collected INTEGER DEFAULT 0, -- 신규 수집 성공 수
    total_skipped INTEGER DEFAULT 0,   -- 중복으로 건너뛴 수
    total_errors INTEGER DEFAULT 0,    -- 처리 중 발생한 에러 수
    status TEXT                        -- RUNNING / COMPLETED
);
```

---

## 한계점 및 개선 아이디어

### 현재 한계점

| 항목 | 현재 상태 | 영향도 |
|------|----------|--------|
| 동기 처리 | 순차적 페이지 수집 | 대량 데이터 수집 시 시간 소요 |
| 정규식 한계 | 패턴 매칭 기반 | 예상 외 포맷 처리 어려움 |
| IP 차단 위험 | 단일 IP 사용 | 장시간 크롤링 시 차단 가능성 |
| 단일 프로세스 | 멀티스레드 미지원 | CPU 코어 활용도 낮음 |

### 개선 로드맵

**Phase 1: 성능 최적화**
- 비동기 배치 수집 (aiohttp)
- 예상 효과: 5페이지 수집 시간 15초 → 3초

**Phase 2: 안정성 강화**
- Proxy Rotation
- Rate Limiter 추가
- Redis 캐싱 레이어

**Phase 3: 정확도 개선**
- Vision Transformer 기반 OCR (TrOCR)
- 예상 효과: 파싱 정확도 85% → 95%

**Phase 4: 확장성**
- PostgreSQL 마이그레이션
- Kubernetes 배포
- 실시간 모니터링 (Grafana)

---

## 참고 자료

**프로젝트 관련**
- 설계 문서: DESIGN.md 참조
- API 문서: 누리장터 공공데이터 포털

**기술 스택 문서**
- [Pydantic 공식 문서](https://docs.pydantic.dev/)
- [Loguru 사용 가이드](https://loguru.readthedocs.io/)
- [Pytest 공식 문서](https://docs.pytest.org/)

---

**마지막 업데이트:** 2026.02.06  
**프로젝트 버전:** 1.0.0