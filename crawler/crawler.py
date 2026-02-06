"""
누리장터 크롤러 오케스트레이션 (Orchestration Layer)
- API Client, Transformer, Storage를 조합하여 전체 크롤링 워크플로우를 관리합니다.
- 각 계층간의 느슨한 결합(Loose Coupling)을 통해 유지보수성과 테스트 용이성을 확보합니다.
- 수집 통계 및 리소스 수명 주기(Lifecycle)를 제어합니다.
"""

import time
import json
from typing import List, Optional
from dataclasses import dataclass
from loguru import logger

from crawler.client import NuriAPIClient
from crawler.transformer import NuriDataTransformer, NoticeDTO, validate_notice_dto, ValidationError
from crawler.storage import CrawlerStorage

# 시스템 운영 안정성을 위한 기본 지연 시간 상수
DEFAULT_DELAY_BETWEEN_PAGES = 1  # 페이지 전환 시 대기 시간 (초)
DEFAULT_DELAY_BETWEEN_DETAILS = 0.5  # 상세 정보 조회 간격 (초)


@dataclass
class CrawlerConfig:
    """
    크롤러 실행을 위한 설정 데이터 객체입니다.
    수집 범위, 페이지당 건수, 상세 정보 수집 여부 등을 제어합니다.
    """
    max_pages: int = 1
    records_per_page: int = 10
    fetch_details: bool = False
    days_back: int = 30
    delay_between_pages: float = DEFAULT_DELAY_BETWEEN_PAGES
    delay_between_details: float = DEFAULT_DELAY_BETWEEN_DETAILS

    def __post_init__(self):
        """설정값에 대한 비즈니스 로직 검증을 수행합니다."""
        if self.max_pages < 1:
            raise ValueError("max_pages는 최소 1 이상이어야 합니다.")
        if self.records_per_page < 1 or self.records_per_page > 100:
            raise ValueError("records_per_page는 1에서 100 사이여야 합니다.")


@dataclass
class CrawlerStats:
    """
    크롤링 작업의 실시간 진행 상태와 최종 결과를 추적하는 통계 객체입니다.
    모니터링 및 리포팅 용도로 사용됩니다.
    """
    total_found: int = 0      # 발견된 총 공고 수
    total_collected: int = 0  # 신규 수집 성공 수
    total_skipped: int = 0    # 중복으로 건너뛴 수
    total_errors: int = 0     # 처리 중 발생한 에러 수
    pages_processed: int = 0  # 성공적으로 처리된 페이지 수
    pages_failed: int = 0     # 조회가 실패한 페이지 수

    def to_dict(self) -> dict:
        """통계 데이터를 저장소(DB) 기록을 위한 딕셔너리 형태로 변환합니다."""
        return {
            'total_found': self.total_found,
            'total_collected': self.total_collected,
            'total_skipped': self.total_skipped,
            'total_errors': self.total_errors,
            'pages_processed': self.pages_processed,
            'pages_failed': self.pages_failed
        }

    def print_summary(self):
        """수집 작업 종료 후 요약 리포트를 로그에 출력합니다."""
        logger.info("=" * 60)
        logger.info("누리장터 데이터 수집 완료 리포트")
        logger.info("-" * 60)
        logger.info(f"처리 페이지: {self.pages_processed}개 (실패: {self.pages_failed}개)")
        logger.info(f"발견 공고: {self.total_found}건")
        logger.info(f"신규 수집: {self.total_collected}건")
        logger.info(f"중복 제외: {self.total_skipped}건")
        logger.info(f"검증 에러: {self.total_errors}건")

        if self.total_found > 0:
            success_rate = (self.total_collected / self.total_found) * 100
            logger.info(f"수집 성공률: {success_rate:.1f}%")

        logger.info("=" * 60)


class NuriCrawler:
    """
    누리장터 크롤링의 핵심 로직을 담당하는 지휘 클래스입니다.
    Client(통신), Transformer(변환), Storage(저장) 부품을 조합하여 작업을 수행합니다.
    """

    def __init__(
            self,
            client: Optional[NuriAPIClient] = None,
            transformer: Optional[NuriDataTransformer] = None,
            storage: Optional[CrawlerStorage] = None,
            db_path: str = "data/crawler_state.db"
    ):
        """
        의존성 주입을 통해 부품을 구성합니다.
        인자가 없을 경우 기본 구현체를 생성하여 유연성을 확보합니다.
        """
        self.client = client or NuriAPIClient()
        self.transformer = transformer or NuriDataTransformer()
        self.storage = storage or CrawlerStorage(db_path)

        self.stats = CrawlerStats()
        logger.info("NuriCrawler 인스턴스가 초기화되었습니다.")

    def run(
            self,
            max_pages: int = 1,
            records_per_page: int = 10,
            fetch_details: bool = False,
            days_back: int = 30
    ) -> List[NoticeDTO]:
        """기본 파라미터를 받아 설정을 생성하고 크롤링을 시작하는 엔트리 포인트입니다."""
        config = CrawlerConfig(
            max_pages=max_pages,
            records_per_page=records_per_page,
            fetch_details=fetch_details,
            days_back=days_back
        )
        return self.run_with_config(config)

    def run_with_config(self, config: CrawlerConfig) -> List[NoticeDTO]:
        """전달된 설정(Config) 객체를 기반으로 전체 수집 프로세스를 실행합니다."""
        logger.info("=" * 60)
        logger.info("누리장터 데이터 수집 세션 시작")
        logger.info(f"설정 정보: 최대 {config.max_pages}페이지, 상세조회: {config.fetch_details}")
        logger.info("=" * 60)

        collected_notices = []
        self.stats = CrawlerStats()  # 매 실행마다 통계 초기화

        # 1. 수집 세션 시작 기록 (DB)
        session_id = self.storage.start_session()

        try:
            # 2. 지정된 페이지 수만큼 순회하며 수집
            for page in range(1, config.max_pages + 1):
                self._process_page(
                    page=page,
                    config=config,
                    collected_notices=collected_notices
                )

                # 페이지 간 요청 딜레이 (서버 부하 방지 및 IP 차단 예방)
                if page < config.max_pages:
                    logger.debug(f"페이지 간 {config.delay_between_pages}초 대기 중...")
                    time.sleep(config.delay_between_pages)

            # 3. 세션 정상 종료 기록
            self.storage.finish_session(session_id, self.stats.to_dict())

        except Exception as e:
            logger.exception(f"크롤링 세션 중 치명적 예외 발생: {e}")
            # 에러 발생 시에도 현재까지의 통계를 저장하여 가시성 확보
            self.storage.finish_session(session_id, self.stats.to_dict())
            raise

        # 최종 결과 요약 출력
        self.stats.print_summary()
        return collected_notices

    def _process_page(
            self,
            page: int,
            config: CrawlerConfig,
            collected_notices: List[NoticeDTO]
    ):
        """특정 페이지의 공고 목록을 조회하고 각 항목을 처리 프로세스로 넘깁니다."""
        logger.info(f"\n[작업 시작] 페이지 {page}/{config.max_pages}")

        # 1. API를 통해 해당 페이지의 원시 데이터(Raw) 요청
        response = self.client.fetch_notice_list(
            page=page,
            records_per_page=config.records_per_page,
            days_back=config.days_back
        )

        if not response:
            logger.warning(f"페이지 {page} 조회 결과가 비어있습니다.")
            self.stats.pages_failed += 1
            return

        self.stats.pages_processed += 1

        # 2. 응답 본문에서 공고 데이터 리스트만 추출 (Transformer 역할)
        raw_notices = self.transformer.extract_notices(response)

        if not raw_notices:
            logger.warning(f"페이지 {page}: 추출된 공고 목록이 없습니다.")
            return

        logger.info(f"페이지 {page}: {len(raw_notices)}건의 공고 발견")
        self.stats.total_found += len(raw_notices)

        # 3. 목록 내 각 공고를 개별적으로 처리
        for idx, raw_notice in enumerate(raw_notices, 1):
            self._process_notice(
                raw_notice=raw_notice,
                idx=idx,
                total=len(raw_notices),
                config=config,
                collected_notices=collected_notices
            )

    def _process_notice(
            self,
            raw_notice: dict,
            idx: int,
            total: int,
            config: CrawlerConfig,
            collected_notices: List[NoticeDTO]
    ):
        """단일 공고에 대한 정규화, 중복 체크, 상세 수집, 검증 및 저장의 전 과정을 관리합니다."""
        try:
            # Step 1: 원시 딕셔너리를 표준 DTO 객체로 변환
            notice_dto = self.transformer.transform_notice(raw_notice)

            if not notice_dto:
                logger.debug(f"[{idx}/{total}] 데이터 변환 실패로 건너뜀")
                self.stats.total_skipped += 1
                return

            # Step 2: 체크포인트 확인 (이미 수집된 데이터는 중복 저장하지 않음)
            if self.storage.is_already_done(notice_dto.notice_id):
                logger.debug(f"[{idx}/{total}] 중복 발견: {notice_dto.notice_id} (건너뜀)")
                self.stats.total_skipped += 1
                return

            # Step 3: 상세 정보 보강 (옵션 설정 시에만 추가 API 호출)
            if config.fetch_details:
                self._fetch_and_enrich_detail(notice_dto, idx, total, config)

            # Step 4: 최종 데이터 정합성 검증 (필수 필드 누락 등 체크)
            try:
                validate_notice_dto(notice_dto)
            except ValidationError as e:
                logger.warning(f"[{idx}/{total}] 비즈니스 규칙 검증 실패 ({notice_dto.notice_id}): {e}")
                self.stats.total_errors += 1
                return

            # Step 5: DB 영구 저장
            self._save_notice(notice_dto, idx, total)

            # Step 6: 메모리 결과 리스트에 추가 (반환용)
            collected_notices.append(notice_dto)

        except Exception as e:
            logger.error(f"[{idx}/{total}] 개별 공고 처리 중 예외 발생: {e}")
            self.stats.total_errors += 1

    def _fetch_and_enrich_detail(
            self,
            notice_dto: NoticeDTO,
            idx: int,
            total: int,
            config: CrawlerConfig
    ):
        """목록에는 없는 상세 정보(예산 등)를 상세조회 API를 통해 가져와 DTO에 채웁니다."""
        try:
            detail_data = self.client.fetch_notice_detail(notice_dto.notice_id)

            if detail_data:
                self.transformer.enrich_with_detail(notice_dto, detail_data)
                logger.debug(f"[{idx}/{total}] 상세정보 보강 완료: {notice_dto.notice_id}")
            else:
                logger.warning(f"[{idx}/{total}] 상세정보 조회가 실패하였습니다: {notice_dto.notice_id}")

            # 상세 조회 간 딜레이 적용 (서버 매너)
            time.sleep(config.delay_between_details)

        except Exception as e:
            logger.error(f"[{idx}/{total}] 상세 정보 수집 중 에러 발생: {e}")

    def _save_notice(self, notice_dto: NoticeDTO, idx: int, total: int):
        """DTO 데이터를 저장소 규격에 맞춰 변환하여 DB에 물리적으로 저장합니다."""
        try:
            # 1. 객체 데이터를 딕셔너리로 직렬화
            save_data = notice_dto.to_dict()

            # 2. raw_data 필드는 JSON 문자열로 변환하여 저장 (데이터 유실 방지)
            save_data['raw_data'] = json.dumps(
                notice_dto.raw_data,
                ensure_ascii=False
            ) if notice_dto.raw_data else '{}'

            # 3. 저장소 레이어로 전달
            self.storage.save_notice(save_data)
            self.stats.total_collected += 1

            logger.debug(f"[{idx}/{total}] DB 저장 완료: {notice_dto.notice_id}")

        except Exception as e:
            logger.error(f"[{idx}/{total}] 저장 프로세스 실패 ({notice_dto.notice_id}): {e}")
            self.stats.total_errors += 1
            raise

    def export_json(self, filepath: str = "data/nuri_notices.json"):
        """수집된 전체 데이터를 DB에서 조회하여 JSON 파일로 내보냅니다."""
        self.storage.export_to_json(filepath)
        logger.success(f"데이터 내보내기 성공 (JSON): {filepath}")

    def export_csv(self, filepath: str = "data/nuri_notices.csv"):
        """수집된 전체 데이터를 DB에서 조회하여 엑셀 호환 CSV 파일로 내보냅니다."""
        self.storage.export_to_csv(filepath)
        logger.success(f"데이터 내보내기 성공 (CSV): {filepath}")

    def get_stats(self) -> dict:
        """메모리 내 실시간 통계와 DB의 누적 통계를 병합하여 반환합니다."""
        db_stats = self.storage.get_stats()
        return {
            **self.stats.to_dict(),
            **db_stats
        }

    def close(self):
        """작업 완료 후 네트워크 세션 및 데이터베이스 연결을 안전하게 종료합니다."""
        self.client.close()
        self.storage.close()
        logger.info("모든 크롤러 리소스가 안전하게 해제되었습니다.")

    def __enter__(self):
        """With 구문(Context Manager) 진입 시 인스턴스 자신을 반환합니다."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """With 구문 종료 시 자동으로 close()를 호출하여 리소스 누수를 방지합니다."""
        self.close()


# 간편 사용을 위한 팩토리 함수
def create_crawler(db_path: str = "data/crawler_state.db") -> NuriCrawler:
    """기본 구성 요소가 설정된 크롤러 인스턴스를 생성하여 반환합니다."""
    return NuriCrawler(db_path=db_path)