"""
누리장터 API 통신 클라이언트 (Network Layer)
- 누리장터 서버와의 POST 통신을 전담하며 세션 및 쿠키를 관리합니다.
- 지수 백오프(Exponential Backoff) 기반의 재시도 로직을 통해 네트워크 불안정성에 대응합니다.
- Rate Limit(429) 발생 시 서버 가이드를 준수하여 자동 대기 후 재시도합니다.
"""

import time
from typing import Optional, Dict
from datetime import datetime, timedelta
import requests
from requests.exceptions import Timeout, ConnectionError
from loguru import logger

# 통신 안정성을 위한 정책 상수 정의
MAX_RETRIES = 3             # 최대 재시도 횟수
RETRY_BACKOFF_BASE = 2      # 재시도 간격 계산을 위한 기수 (초)
RETRY_BACKOFF_MAX = 10      # 최대 대기 시간 제한 (초)
REQUEST_TIMEOUT = 30        # API 응답 대기 제한 시간 (초)
RATE_LIMIT_WAIT = 60        # 429 발생 시 기본 대기 시간 (초)


class APIError(Exception):
    """API 호출 과정에서 발생하는 최상위 예외 클래스입니다."""
    pass


class RetryableAPIError(APIError):
    """서버 일시 오류나 타임아웃 등 재시도 시 성공 가능성이 있는 에러입니다."""
    pass


class NonRetryableAPIError(APIError):
    """400 Bad Request 등 로직 수정이 필요한 치명적 에러입니다."""
    pass


class NuriAPIClient:
    """
    누리장터 서버의 인터페이스 스펙을 준수하는 전문 통신 클래스입니다.
    비즈니스 로직과 분리되어 순수하게 데이터 송수신 및 세션 관리만 수행합니다.
    """

    def __init__(
            self,
            base_url: str = "https://nuri.g2b.go.kr",
            timeout: int = REQUEST_TIMEOUT,
            max_retries: int = MAX_RETRIES
    ):
        self.base_url = base_url
        self.timeout = timeout
        self.max_retries = max_retries

        # API 엔드포인트 설정
        self.list_endpoint = f"{base_url}/nn/nnb/nnba/selectBidPbancList.do"
        self.detail_endpoint = f"{base_url}/nn/nnb/nnbb/selectBidNoceDetl.do"

        # 세션 유지를 통해 매 요청마다 핸드셰이크가 발생하는 오버헤드 방지
        self.session = self._create_session()

        logger.info(f"NuriAPIClient 초기화 완료 (timeout={timeout}s, max_retries={max_retries})")

    def _create_session(self) -> requests.Session:
        """브라우저 환경을 모사하고 세션 쿠키를 유지하기 위한 설정을 수행합니다."""
        session = requests.Session()
        session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
            'Accept': 'application/json, text/javascript, */*; q=0.01',
            'Content-Type': 'application/json;charset=UTF-8',
            'X-Requested-With': 'XMLHttpRequest',
            'Referer': 'https://nuri.g2b.go.kr/' # 보안 정책 대응용 레퍼러 설정
        })
        return session

    def _make_request(
            self,
            url: str,
            payload: dict,
            context: str = "API 요청"
    ) -> Optional[dict]:
        """
        견고한 통신을 위한 메인 요청 메서드입니다.
        상태 코드별 처리 전략(재시도 여부 결정)을 포함합니다.
        """
        last_exception = None

        for attempt in range(1, self.max_retries + 1):
            try:
                logger.debug(f"{context} 시도 중... (시도 {attempt}/{self.max_retries})")

                response = self.session.post(
                    url,
                    json=payload,
                    timeout=self.timeout
                )

                # 1. Rate Limit 대응 (서버 부하 조절 지시 준수)
                if response.status_code == 429:
                    retry_after = int(response.headers.get('Retry-After', RATE_LIMIT_WAIT))
                    logger.warning(f"Rate limit 감지. {retry_after}초 대기 후 재시도합니다.")
                    time.sleep(retry_after)
                    continue

                # 2. 서버 에러 (5xx) - 일시적 문제일 가능성이 높아 재시도 수행
                if 500 <= response.status_code < 600:
                    if attempt < self.max_retries:
                        # 지수 백오프 적용: 2s, 4s, 8s... 순으로 대기
                        wait_time = min(RETRY_BACKOFF_BASE ** attempt, RETRY_BACKOFF_MAX)
                        logger.warning(f"서버 오류 {response.status_code}. {wait_time}초 후 다시 시도합니다.")
                        time.sleep(wait_time)
                        continue
                    return None

                # 3. 클라이언트 에러 (4xx) - 요청 값이 잘못되었으므로 즉시 중단
                if 400 <= response.status_code < 500:
                    error_msg = f"HTTP {response.status_code}: {response.text[:200]}"
                    raise NonRetryableAPIError(error_msg)

                # 4. 정상 응답 (200)
                if response.status_code == 200:
                    return response.json()

            except (Timeout, ConnectionError) as e:
                # 네트워크 지연이나 단절 시 지수 백오프 후 재시도
                last_exception = e
                if attempt < self.max_retries:
                    wait_time = min(RETRY_BACKOFF_BASE ** attempt, RETRY_BACKOFF_MAX)
                    logger.warning(f"네트워크 오류 ({type(e).__name__}). {wait_time}초 후 재시도합니다.")
                    time.sleep(wait_time)
                    continue

            except Exception as e:
                # 예상치 못한 로직 에러는 재시도 없이 상위로 전파
                logger.exception(f"통신 중 예상치 못한 에러 발생: {e}")
                raise NonRetryableAPIError(f"Unexpected error: {e}")

        logger.error(f"{context} 최종 실패: {self.max_retries}회 시도 초과. (마지막 에러: {last_exception})")
        return None

    def fetch_notice_list(
            self,
            page: int = 1,
            records_per_page: int = 10,
            days_back: int = 30
    ) -> Optional[dict]:
        """입찰공고 목록을 페이지 단위로 조회합니다."""
        payload = self._build_list_payload(page, records_per_page, days_back)
        return self._make_request(url=self.list_endpoint, payload=payload, context=f"목록 조회({page}p)")

    def fetch_notice_detail(
            self,
            bid_no: str,
            bid_ord: str = "000"
    ) -> Optional[dict]:
        """특정 공고의 상세 정보를 조회합니다."""
        payload = self._build_detail_payload(bid_no, bid_ord)
        return self._make_request(url=self.detail_endpoint, payload=payload, context=f"상세 조회({bid_no})")

    def _build_list_payload(
            self,
            page: int,
            records_per_page: int,
            days_back: int
    ) -> dict:
        """
        지원님이 분석하신 누리장터 목록 조회용 복합 파라미터를 생성합니다.
        날짜 범위 및 페이지네이션 정보가 포함됩니다.
        """
        today = datetime.now()
        start_date = today - timedelta(days=days_back)
        end_date = today + timedelta(days=30)

        return {
            "dlParamM": {
                "bidPbancNo": "", "bidPbancOrd": "", "bidPbancNm": "",
                "prcmBsneSeCd": "", "bidPbancPgstCd": "", "bidMthdCd": "",
                "currentPage": page, "frgnrRprsvYn": "", "kbrdrId": "",
                "onbsPrnmntEdDt": end_date.strftime("%Y%m%d"),
                "onbsPrnmntStDt": today.strftime("%Y%m%d"),
                "pbancInstUntyGrpNo": "", "pbancKndCd": "",
                "pbancPstgEdDt": today.strftime("%Y%m%d"),
                "pbancPstgStDt": start_date.strftime("%Y%m%d"),
                "pbancPstgYn": "Y", "pbancSttsCd": "", "pdngYn": "",
                "recordCountPerPage": str(records_per_page),
                "rowNum": "", "scsbdMthdCd": "", "stdCtrtMthdCd": "",
                "untyGrpNo": "", "usrTyCd": ""
            }
        }

    def _build_detail_payload(self, bid_no: str, bid_ord: str) -> dict:
        """지원님이 분석하신 상세 조회 전용 페이로드를 구성합니다."""
        return {
            "dlSrchCndtM": {
                "pbancFlag": "", "bidPbancNo": bid_no, "bidPbancOrd": bid_ord,
                "bidClsfNo": "0", "bidPrgrsOrd": "000", "bidPbancNm": "",
                "bidPbancPgstCd": "", "flag": "bidDtl", "frgnrRprsvYn": "",
                "kbrdrId": "", "odn3ColCn": "", "paramGbn": "1",
                "pbancInstUntyGrpNo": "", "pbancPstgEdDt": "", "pbancPstgStDt": "",
                "prcmBsneSeCd": "", "pstNo": bid_no, "recordCountPerPage": "",
                "rowNum": "", "untyGrpNo": ""
            }
        }

    def close(self):
        """작업 완료 후 커넥션 풀을 안전하게 반환합니다."""
        self.session.close()
        logger.debug("API 세션 종료")

    # Resource 관리를 위한 Context Manager 지원
    def __enter__(self): return self
    def __exit__(self, exc_type, exc_val, exc_tb): self.close()