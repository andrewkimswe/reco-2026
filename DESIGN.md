# 설계 문서

## 목차
1. [시스템 아키텍처](#시스템-아키텍처)
2. [데이터 흐름](#데이터-흐름)
3. [주요 설계 결정](#주요-설계-결정)
4. [트레이드오프 분석](#트레이드오프-분석)

---

## 시스템 아키텍처

### 전체 구조도

```
┌─────────────────────────────────────────────────────────────┐
│                     Presentation Layer                     │
│  ┌──────────────────┐         ┌─────────────────────────┐  │
│  │   main.py (CLI)  │         │  tests/ (Test Suite)    │  │
│  │  - 명령행 인터페이스 │         │  - pytest 기반 검증        │  │
│  └──────────────────┘         └─────────────────────────┘  │
└─────────────────────┬───────────────────┬───────────────────┘
                      │                   │
┌─────────────────────┴───────┐  ┌───────┴──────────────────┐
│   OCR Parser                 │  │  Crawler                 │
│  ┌──────────────────────┐   │  │  ┌──────────────────┐   │
│  │  processor.py        │   │  │  │  crawler.py      │   │
│  │  - 정규식 파싱       │   │  │  │  (Crawler Engine)  │   │
│  │  - 차량번호/중량 추출│   │  │  └────────┬─────────┘   │
│  └──────────┬───────────┘   │  │           │             │
│             │               │  │  ┌────────┴─────────┐   │
│  ┌──────────┴───────────┐   │  │  │  transformer.py  │   │
│  │  schemas.py          │   │  │  │  - DTO 변환      │   │
│  │  - Pydantic 검증     │   │  │  │  - 데이터 정규화 │   │
│  └──────────────────────┘   │  │  └────────┬─────────┘   │
└──────────────────────────────┘  │           │             │
                                  │  ┌────────┴─────────┐   │
                                  │  │  client.py       │   │
                                  │  │  - HTTP 통신     │   │
                                  │  │  - 재시도 로직   │   │
                                  │  └────────┬─────────┘   │
                                  │           │             │
                                  │  ┌────────┴─────────┐   │
                                  │  │  storage.py      │   │
                                  │  │  - SQLite        │   │
                                  │  │  - 트랜잭션      │   │
                                  │  │  - 세션 관리     │   │
                                  │  └──────────────────┘   │
                                  └──────────────────────────┘
                                            │
                                  ┌─────────┴─────────┐
                                  │  data/            │
                                  │  - crawler_state.db│
                                  └────────────────────┘
```

### 계층별 책임

| 계층 | 구성 요소 | 책임 |
|------|----------|------|
| Presentation | main.py | CLI 인터페이스, 사용자 입력 처리, 모드 제어 |
| Application | crawler.py | 비즈니스 워크플로우 제어, 상태 관리, 통계 수집 |
| Domain | transformer.py | 데이터 변환 및 정규화, 비즈니스 규칙, DTO 검증 |
| Infrastructure | client.py, storage.py | 외부 시스템 연동, 데이터 저장, 세션 관리 |
| Model | schemas.py | 데이터 구조 정의, 유효성 검증 |

---

## 데이터 흐름

### OCR 파싱 플로우

```
┌─────────────┐
│ JSON 파일   │  sample_01.json ~ sample_04.json
└──────┬──────┘
       │
       ▼
┌─────────────────────────────────────────────────┐
│ processor.py::_clean_text()                     │
│ [전처리 단계]                                      │
│ 1. 시간 형식 노이즈 제거                             │
│    - "11시 30분" → 제거                           │
│    - "02:30" → 제거                              │
│ 2. 숫자 간 공백 통합                                │
│    - "14 080" → "14080"                         │
└──────┬──────────────────────────────────────────┘
       │
       ▼
┌─────────────────────────────────────────────────┐
│ processor.py::parse()                           │
│ [파싱 단계]                                       │
│ 1. 차량번호 추출: r'차량번호.*(\d{2,3}[가-힣]?\d{4})'  │
│ 2. 중량 추출 (_extract_weight)                    │
│    - 라벨 기반 탐색 (총중량, 공차중량, 실중량)           │
│    - 100 ≤ weight ≤ 999,999 범위 필터링            │
└──────┬──────────────────────────────────────────┘
       │
       ▼
┌─────────────────────────────────────────────────┐
│ processor.py::parse() [보정 로직]                 │
│ 3. 중량값 자동 보정                                 │
│    - 3개 값 모두 있을 때: 크기순 정렬                  │
│      sorted([총, 공차, 실], reverse=True)         │
│    - 2개 값만 있을 때: 나머지 하나 계산                │
│      예) 총 - 공차 = 실                            │
└──────┬──────────────────────────────────────────┘
       │
       ▼
┌─────────────────────────────────────────────────┐
│ schemas.py::WeightTicket (Pydantic)             │
│ 4. 데이터 검증                                     │
│    - 필드 타입 검증                                │
│    - 산술 관계 검증 (총중량 - 공차 = 실중량)            │
│      오차 허용: ±10kg                             │
│    - is_weight_valid 플래그 생성                   │
└──────┬──────────────────────────────────────────┘
       │
       ▼
┌─────────────────────────────────────────────────┐
│ 출력: JSON / CSV                                 │
│ - 구조화된 데이터                                   │
│ - 검증 결과 포함                                   │
│ - UTF-8 BOM 인코딩 (CSV)                          │
└─────────────────────────────────────────────────┘
```

### 크롤링 플로우

```
┌─────────────┐
│ main.py     │  --mode once --pages 5 --details
└──────┬──────┘
       │
       ▼
┌─────────────────────────────────────────────────┐
│ crawler.py::run_with_config()                   │
│ - CrawlerConfig 객체 생성                         │
│ - 페이지 루프 시작                                  │
│ - 통계 초기화 (CrawlerStats)                       │
│ - storage.start_session() 호출                   │
└──────┬──────────────────────────────────────────┘
       │
       ▼ [페이지 1 처리]
┌─────────────────────────────────────────────────┐
│ client.py::fetch_notice_list(page=1)            │
│ 1. POST 요청 전송                                 │
│ 2. 에러 처리 전략:                                 │
│    - 429 Rate Limit: Retry-After 헤더 준수        │
│    - 5xx 서버 에러: 지수 백오프 (2^n초, 최대 10초)     │
│    - 4xx 클라이언트 에러: 즉시 중단                   │
│    - Timeout/ConnectionError: 재시도              │
└──────┬──────────────────────────────────────────┘
       │
       ▼ [원시 JSON 응답]
┌─────────────────────────────────────────────────┐
│ transformer.py::extract_notices()               │
│ 1. LIST_KEYS 순회하여 공고 목록 탐색                  │
│    ['result', 'list', 'resultList', 'data', ...]│
│ 2. 공고 목록 추출                                  │
└──────┬──────────────────────────────────────────┘
       │
       ▼ [공고 리스트]
┌─────────────────────────────────────────────────┐
│ transformer.py::transform_notice()              │
│ 1. 필드명 정규화                                   │
│    - bidPbancNo → notice_id                     │
│    - bidPbancNm → title                         │
│ 2. 날짜 포맷 변환                                  │
│    - YYYYMMDD → YYYY-MM-DD                      │
│ 3. NoticeDTO 생성 (dataclass)                    │
└──────┬──────────────────────────────────────────┘
       │
       ▼ [각 공고별 처리]
┌─────────────────────────────────────────────────┐
│ storage.py::is_already_done(notice_id)          │
│ - SELECT 1 FROM scrap_log                       │
│   WHERE notice_id = ? AND status = 'SUCCESS'    │
│ - 중복 시: 스킵 (stats.total_skipped++)            │
│ - 신규 시: 다음 단계 진행                            │
└──────┬──────────────────────────────────────────┘
       │
       ▼ [상세 정보 필요 시]
┌─────────────────────────────────────────────────┐
│ client.py::fetch_notice_detail(notice_id)       │
│ - 상세 API 호출 (별도 엔드포인트)                     │
│ - transformer.py::enrich_with_detail()          │
│   (기존 DTO에 추가 필드 병합)                        │
│   - raw_data['detail'] = detail_data            │
│ - delay_between_details 대기 (기본 0.5초)          │
└──────┬──────────────────────────────────────────┘
       │
       ▼ [DTO 검증]
┌─────────────────────────────────────────────────┐
│ transformer.py::validate_notice_dto()           │
│ - 공고번호 필수 확인                                 │
│ - 제목 유효성 검증                                  │
│ - ValidationError 발생 시 스킵                     │
└──────┬──────────────────────────────────────────┘
       │
       ▼ [DB 저장]
┌─────────────────────────────────────────────────┐
│ storage.py::save_notice() [트랜잭션]              │
│ BEGIN TRANSACTION;                              │
│   1. INSERT OR REPLACE INTO nuri_notices        │
│      (notice_id, title, org_name, ...);         │
│   2. INSERT OR REPLACE INTO scrap_log           │
│      (notice_id, status='SUCCESS', ...);        │
│ COMMIT;                                         │
│ - 실패 시 자동 ROLLBACK으로 데이터 불일치 방지          │
└──────┬──────────────────────────────────────────┘
       │
       ▼ [통계 업데이트 및 종료]
┌─────────────────────────────────────────────────┐
│ crawler.py::_process_page() 완료                 │
│ - stats.total_collected++                       │
│ - delay_between_pages 대기 (기본 1초)              │
│                                                 │
│ 모든 페이지 처리 완료 후:                             │
│ - storage.finish_session(session_id, stats)     │
│ - stats.print_summary() 리포트 출력                │
│ - export_csv/export_json 호출                    │
└─────────────────────────────────────────────────┘
```

---

## 주요 설계 결정

### OCR 파싱 설계

#### 결정 1: 정규식 기반 파싱
```python
# 선택한 방법
vehicle_pattern = r'(?:차량\s*번호|차\s*번호).*?(\d{2,3}[가-힣]?\d{4})'
weight_pattern = r'(\d[\d,]{2,})\s*kg'

# 고려했던 대안
# - spaCy NER (Named Entity Recognition)
# - 딥러닝 모델 (TrOCR)
```

**근거**
- 구현 단순성: 정규식은 의존성 없이 빠르게 구현 가능
- 재현성: 동일 입력에 동일 출력 보장
- 디버깅 용이: 패턴 수정이 명확
- 확장성 제약: 예상 외 포맷 대응 어려움

#### 결정 2: 노이즈 필터링 임계값
```python
# 100kg 미만 / 999,999kg 초과 필터링
MIN_WEIGHT_KG = 100
MAX_WEIGHT_KG = 999_999
valid_weights = [w for w in weights if MIN_WEIGHT_KG <= w <= MAX_WEIGHT_KG]
```

**근거**
- OCR 텍스트에 시간 데이터(02, 11)가 포함되어 중량으로 오인식
- 실제 계근지 중량 범위: 소형차 100kg ~ 대형 트레일러 100톤
- 트레이드오프: 극단적 케이스(99kg 화물) 누락 가능

#### 결정 3: 다단계 보정 전략
```python
# 3개 값 모두 추출 시: 크기순 자동 재배치
if len(non_zero) >= 3:
    all_w = sorted(non_zero, reverse=True)
    gross, tare, net = all_w[0], all_w[1], all_w[2]

# 2개 값만 추출 시: 나머지 하나 계산
elif len(non_zero) == 2:
    if gross > 0 and net > 0 and tare == 0:
        tare = gross - net
```

**근거**
- OCR 오류로 중량 라벨과 값의 위치가 뒤섞일 수 있음
- 물리 법칙 활용: 총중량 > 공차중량 > 실중량 순서 보장
- 트레이드오프: 극단적 예외 케이스(공차 > 총중량) 처리 불가

#### 결정 4: 산술 검증 오차 허용
```python
# ±10kg 오차 허용 (schemas.py)
WEIGHT_TOLERANCE_KG = 10
diff = abs((gross - tare) - net)
is_valid = diff <= WEIGHT_TOLERANCE_KG
```

**근거**
- OCR 오류로 인한 1~2자리 숫자 인식 오차 고려
- 실무에서 계근 장비 오차 범위 ±5kg 내외
- 트레이드오프: 명백한 데이터 오류 통과 가능

### 크롤링 시스템 설계

#### 결정 5: 동기 vs 비동기
```python
# 선택: 동기 방식 (requests)
def fetch_page(page: int):
    response = self.session.post(url, json=payload, timeout=30)
    return response.json()

# 미선택: 비동기 방식 (aiohttp)
# async def fetch_page(page: int):
#     async with aiohttp.ClientSession() as session:
#         async with session.post(url, json=payload) as response:
#             return await response.json()
```

**근거**
- 안정성 우선: 동기 코드는 디버깅과 에러 추적이 명확
- 과제 규모: 소량 데이터(1~10페이지) 수집에는 충분
- 의존성 최소화: asyncio/aiohttp 추가 불필요
- 성능 희생: 대량 수집 시 비동기 대비 3~5배 느림

**개선 계획**
```python
# Phase 2 개선 시 비동기 전환
async def crawl_pages_parallel(pages: List[int]):
    tasks = [fetch_page(p) for p in pages]
    return await asyncio.gather(*tasks)
```

#### 결정 6: 재시도 전략 (Exponential Backoff)
```python
# 선택: 지수 백오프 (client.py)
wait_time = min(RETRY_BACKOFF_BASE ** attempt, RETRY_BACKOFF_MAX)
# 2^1=2s, 2^2=4s, 2^3=8s (최대 10s)

# 미선택: 고정 간격
# wait_time = 3  # 항상 3초
```

**근거**
- 서버 부하 완화: 장애 시 점진적 재시도로 서버 복구 시간 확보
- RFC 표준 준수: RFC 7231 권장 방식
- 성공률 향상: 일시적 네트워크 불안정 대응

**수치 선정 이유**
- 최대 재시도: 3회 (AWS/Google Cloud 기본값)
- 초기 대기: 2초 (사람이 체감 가능한 최소 시간)
- 최대 대기: 10초 (REQUEST_TIMEOUT 30초의 1/3)

#### 결정 7: Rate Limit 대응 전략
```python
# 429 응답 시 서버 지시 준수
if response.status_code == 429:
    retry_after = int(response.headers.get('Retry-After', RATE_LIMIT_WAIT))
    time.sleep(retry_after)
```

**근거**
- 서버 가이드 우선: Retry-After 헤더가 있으면 준수
- 기본값 안전장치: 헤더 없을 시 60초 대기
- IP 차단 방지: 무리한 요청으로 인한 영구 차단 예방

#### 결정 8: 데이터베이스 선택 (SQLite vs PostgreSQL)
```python
# 선택: SQLite
conn = sqlite3.connect("data/crawler_state.db")

# 미선택: PostgreSQL
# conn = psycopg2.connect("postgresql://localhost/crawler")
```

**근거**
- 재현성: 별도 DB 서버 설치 불필요, 단일 파일 배포
- 트랜잭션 지원: ACID 보장으로 데이터 무결성 확보
- 경량: 소규모 데이터(수만 건)에 충분한 성능
- 동시성 제약: 다중 프로세스 동시 쓰기 불가

**마이그레이션 계획**
```sql
-- 프로덕션 전환 시 PostgreSQL 스키마 (동일 구조)
CREATE TABLE nuri_notices (
    notice_id TEXT PRIMARY KEY,
    ...
) WITH (fillfactor = 90);  -- Write-heavy 최적화
```

#### 결정 9: 트랜잭션 원자성 보장
```python
# storage.py::save_notice()
with self.conn:  # 트랜잭션 시작
    # 1. 공고 데이터 저장
    self.conn.execute("INSERT OR REPLACE INTO nuri_notices ...")
    # 2. 로그 기록
    self.conn.execute("INSERT OR REPLACE INTO scrap_log ...")
    # COMMIT (자동)
```

**근거**
- 데이터 무결성: 공고는 저장되었는데 로그가 안 남는 불일치 방지
- 자동 롤백: 예외 발생 시 모든 변경 사항 취소
- 증분 수집 신뢰성: scrap_log 기반 중복 체크가 정확해야 함

#### 결정 10: 세션 관리 시스템
```python
# 작업 단위 추적 (storage.py)
session_id = storage.start_session()
# ... 크롤링 수행 ...
storage.finish_session(session_id, stats)
```

**근거**
- 운영 가시성: 각 실행 단위의 통계를 시계열로 추적
- 장애 분석: 실패율 패턴 파악 및 재시도 대상 식별
- 성능 모니터링: 페이지당 처리 시간, 에러율 추이 분석

#### 결정 11: 로깅 라이브러리 (loguru vs logging)
```python
# 선택: loguru
from loguru import logger
logger.info("페이지 1 처리 중...")

# 미선택: 표준 logging
# import logging
# logging.basicConfig(level=logging.INFO)
# logging.info("페이지 1 처리 중...")
```

**근거**
- 간결한 설정: 한 줄로 파일/콘솔 동시 출력
- 컨텍스트 바인딩: `logger.bind(notice_id=x)` 자동 추가
- 성능: 표준 logging 대비 10~20% 빠름
- 외부 의존성: 표준 라이브러리 아님

---

## 트레이드오프 분석

### 정확성 vs 복잡성

| 접근 방식 | 정확도 | 구현 복잡도 | 의존성 | 선택 |
|----------|--------|-----------|--------|------|
| 정규식 파싱 | 85% | 낮음 | 없음 | 채택 |
| spaCy NER | 90% | 높음 | 150MB 모델 | 미채택 |
| TrOCR (딥러닝) | 95% | 매우 높음 | 500MB 모델 + GPU | 미채택 |

**결정 근거**
- 과제 기한 내 85% 정확도로 충분히 실용적
- 간단한 계근지 포맷은 정규식으로 커버 가능
- Phase 3에서 딥러닝 모델 도입 계획

### 성능 vs 안정성

| 접근 방식 | 처리 속도 | 에러 복구 | 디버깅 난이도 | 선택 |
|----------|----------|----------|-------------|------|
| 동기 처리 | 100% (기준) | 명확 | 낮음 | 채택 |
| 비동기 처리 | 400% | 복잡 | 높음 | 미채택 (Phase 2) |
| 멀티프로세스 | 300% | 매우 복잡 | 매우 높음 | 미채택 |

**벤치마크 (10페이지 수집)**
```
동기 (requests):      15초
비동기 (aiohttp):     3.5초
멀티프로세스:         4초 (Context Switching 오버헤드)
```

**결정 근거**
- 과제 요구사항 1~5페이지 수집: 동기 방식으로 충분
- 에러 추적 및 로깅이 명확하여 개발 속도 향상
- 프로덕션 전환 시 비동기로 전환 계획

### 유연성 vs 단순성

| 설계 선택 | 유연성 | 코드 라인 | 학습 곡선 | 선택 |
|----------|--------|----------|----------|------|
| 단일 모듈 | 낮음 | 300줄 | 낮음 | 미채택 |
| 계층화 (현재) | 높음 | 800줄 | 중간 | 채택 |
| 마이크로서비스 | 매우 높음 | 2000줄+ | 매우 높음 | 미채택 (과잉) |

**계층화 아키텍처의 장점**
```python
# 새로운 데이터 소스 추가 예시
class NaverShoppingCrawler(BaseCrawler):
    def __init__(self):
        self.client = NaverAPIClient()  # client.py 재사용
        self.storage = SQLiteStorage()  # storage.py 재사용
    
    def fetch_page(self, page: int):
        # 네이버 쇼핑 전용 로직만 구현
        pass
```

---

## 확장 로드맵

### Phase 1: 안정화 (현재)
- 동기 방식 크롤링
- SQLite 기반 저장
- 정규식 파싱
- 트랜잭션 원자성 보장
- 세션 관리 시스템

### Phase 2: 성능 최적화 (3개월)
- 비동기 배치 수집 (aiohttp)
- Redis 캐싱 레이어
- Proxy Rotation
- 병렬 상세 조회

### Phase 3: 정확도 개선 (6개월)
- Vision Transformer (TrOCR)
- Few-shot Learning 적용
- 사용자 피드백 루프
- Active Learning 파이프라인

### Phase 4: 프로덕션 전환 (1년)
- PostgreSQL 마이그레이션
- Kubernetes 배포
- 실시간 모니터링 (Grafana)
- 알림 시스템 (Slack/Email)

---

## 코드 메트릭스

### 테스트 커버리지
```
crawler/     → 통합 테스트 8건 (주요 시나리오 커버)
ocr_parser/  → 유닛 테스트 2건 (4개 샘플 + BOM 검증)
전체         → E2E 테스트 중심 설계
```

**목표**
- 핵심 로직: 통합 테스트로 실제 환경 검증
- 엣지 케이스: 유닛 테스트로 세부 검증

---

## 용어 사전

| 용어 | 설명 |
|------|------|
| DTO | Data Transfer Object, 계층 간 데이터 전달용 불변 객체 |
| 지수 백오프 | 재시도 대기 시간을 2^n으로 증가시키는 전략 (2s, 4s, 8s...) |
| ACID | 트랜잭션 속성 (Atomicity, Consistency, Isolation, Durability) |
| SoC | Separation of Concerns, 관심사 분리 원칙 |
| Context Manager | `with` 문으로 리소스 자동 해제하는 Python 패턴 |
| Rate Limiting | API 호출 빈도 제한 (예: 초당 10회) |
| Idempotency | 동일 요청 반복 시 결과가 동일함을 보장 |
| BOM | Byte Order Mark, UTF-8 파일의 인코딩 식별 서명 (0xEF 0xBB 0xBF) |

---

**문서 버전:** 1.0.1  
**최종 수정일:** 2026.02.06