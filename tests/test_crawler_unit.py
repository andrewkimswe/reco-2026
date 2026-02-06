"""
누리장터 크롤러 시스템 단위 테스트 (Unit Test)
- 목적: 외부 의존성(API, DB)을 격리(Mock)하여 각 계층의 로직을 독립적으로 검증합니다.
- 테스트 전략: Given-When-Then 패턴을 사용하여 가독성과 유지보수성을 확보합니다.
- 범위: 통신 계층(Client), 변환 계층(Transformer), 제어 계층(Crawler) 및 데이터 무결성 검증.
"""

import pytest
from unittest.mock import Mock, patch

from crawler.client import NuriAPIClient, NonRetryableAPIError
from crawler.transformer import NuriDataTransformer, NoticeDTO, validate_notice_dto, ValidationError
from crawler.crawler import NuriCrawler, CrawlerConfig, CrawlerStats
from crawler.storage import CrawlerStorage


class TestNuriAPIClient:
    """API 통신 계층 테스트: 네트워크 장애 복구력 및 상태 코드별 대응 로직을 검증합니다."""

    @pytest.fixture
    def client(self):
        """테스트 효율을 위해 재시도 횟수를 제한한 테스트용 클라이언트를 생성합니다."""
        return NuriAPIClient(max_retries=2)

    @patch('requests.Session.post')
    def test_fetch_notice_list_success(self, mock_post, client):
        """정상적인 API 응답 시 리스트 데이터가 올바르게 반환되는지 확인합니다."""
        # Given: 서버로부터 성공(200) 응답 및 샘플 데이터 설정
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'result': [{'bidPbancNo': '20240001', 'bidPbancNm': '테스트 공고'}]
        }
        mock_post.return_value = mock_response

        # When: 목록 조회 함수 실행
        result = client.fetch_notice_list(page=1, records_per_page=10)

        # Then: 결과 데이터 존재 여부 및 실제 API 호출 발생 확인
        assert result is not None
        assert 'result' in result
        assert len(result['result']) == 1
        mock_post.assert_called_once()

    @patch('requests.Session.post')
    def test_fetch_notice_list_timeout_with_retry(self, mock_post, client):
        """일시적 네트워크 타임아웃 발생 시, 설정된 횟수만큼 재시도(Retry)하는지 검증합니다."""
        from requests.exceptions import Timeout

        # Given: 첫 시도는 타임아웃 실패, 두 번째 시도에서 성공하는 시나리오 구성
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {'result': []}
        mock_post.side_effect = [Timeout(), mock_response]

        # When: 조회 요청 수행
        result = client.fetch_notice_list(page=1)

        # Then: 총 2번의 요청이 발생했는지(재시도 여부) 확인
        assert result is not None
        assert mock_post.call_count == 2

    @patch('requests.Session.post')
    def test_fetch_notice_list_rate_limit(self, mock_post, client):
        """서버 부하 제한(429) 응답 시, Retry-After 헤더를 준수하여 재시도하는지 확인합니다."""
        # Given: 429 에러 후 성공하는 시나리오
        mock_rate_limit = Mock()
        mock_rate_limit.status_code = 429
        mock_rate_limit.headers = {'Retry-After': '1'}

        mock_success = Mock()
        mock_success.status_code = 200
        mock_success.json.return_value = {'result': []}
        mock_post.side_effect = [mock_rate_limit, mock_success]

        # When: 요청 수행
        result = client.fetch_notice_list(page=1)

        # Then: 재시도 로직이 작동하여 최종적으로 데이터를 가져왔는지 확인
        assert result is not None
        assert mock_post.call_count == 2

    @patch('requests.Session.post')
    def test_fetch_notice_list_client_error(self, mock_post, client):
        """400(Bad Request)과 같은 클라이언트 에러는 재시도 없이 즉시 중단하는지 확인합니다."""
        # Given: 잘못된 요청 시나리오 설정
        mock_response = Mock()
        mock_response.status_code = 400
        mock_response.text = "Bad Request"
        mock_post.return_value = mock_response

        # When & Then: 재시도 불가능한 에러(NonRetryableAPIError)가 발생하는지 검증
        with pytest.raises(NonRetryableAPIError):
            client.fetch_notice_list(page=1)

    @patch('requests.Session.post')
    def test_fetch_notice_detail_success(self, mock_post, client):
        """특정 공고의 상세 정보 요청이 정상적으로 처리되는지 확인합니다."""
        # Given
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {'detailInfo': {'bidPbancNo': '20240001'}}
        mock_post.return_value = mock_response

        # When
        result = client.fetch_notice_detail('20240001')

        # Then
        assert result is not None
        assert 'detailInfo' in result


class TestNuriDataTransformer:
    """데이터 변환 계층 테스트: 복잡한 API 응답을 표준 규격(DTO)으로 정규화하는 로직을 검증합니다."""

    @pytest.fixture
    def transformer(self):
        return NuriDataTransformer()

    def test_extract_notices_from_result_key(self, transformer):
        """API 응답의 다양한 루트 키('result', 'list' 등)를 유연하게 처리하는지 확인합니다."""
        # Given: 'result' 키에 데이터가 담긴 경우
        response = {'result': [{'bidPbancNo': '001'}, {'bidPbancNo': '002'}]}

        # When: 리스트 추출 실행
        notices = transformer.extract_notices(response)

        # Then
        assert len(notices) == 2
        assert notices[0]['bidPbancNo'] == '001'

    def test_extract_notices_from_list_key(self, transformer):
        """'list' 키 구조의 응답에서도 데이터를 정상 추출하는지 확인합니다."""
        response = {'list': [{'bidPbancNo': '001'}]}
        notices = transformer.extract_notices(response)
        assert len(notices) == 1

    def test_extract_notices_empty_response(self, transformer):
        """데이터가 없는 빈 응답이 왔을 때 에러 없이 빈 리스트를 반환하는지 확인합니다."""
        response = {}
        notices = transformer.extract_notices(response)
        assert len(notices) == 0

    def test_transform_notice_success(self, transformer):
        """원시 데이터가 표준 DTO 객체로 필드 매핑 및 날짜 포맷팅이 완료되는지 확인합니다."""
        # Given: 날짜 형식이 정규화되지 않은 원시 데이터
        raw_notice = {
            'bidPbancNo': '20240001',
            'bidPbancNm': '테스트 공고',
            'grpNm': '테스트 기관',
            'prcmBsneSeCdNm': '물품',
            'pbancPstgDt': '20240205',  # YYYYMMDD
            'onbsPrnmntEdDt': '20240220'
        }

        # When: 변환 수행
        dto = transformer.transform_notice(raw_notice)

        # Then: DTO 필드 검증 및 날짜 포맷(YYYY-MM-DD) 확인
        assert dto is not None
        assert dto.notice_id == '20240001'
        assert dto.announce_date == '2024-02-05'
        assert dto.due_date == '2024-02-20'

    def test_transform_notice_missing_id(self, transformer):
        """필수 식별자인 공고 번호가 없을 경우 변환을 거부(None 반환)하는지 확인합니다."""
        raw_notice = {'bidPbancNm': '공고'}
        dto = transformer.transform_notice(raw_notice)
        assert dto is None

    def test_transform_notice_with_defaults(self, transformer):
        """일부 필드가 누락되어도 기본값(제목없음 등)으로 객체를 생성하는지 확인합니다."""
        raw_notice = {'bidPbancNo': '20240001'}
        dto = transformer.transform_notice(raw_notice)
        assert dto is not None
        assert dto.title == '제목없음'
        assert dto.org_name == '기관없음'

    def test_enrich_with_detail(self, transformer):
        """상세 페이지 조회를 통해 얻은 추가 정보가 DTO에 정상적으로 보강되는지 확인합니다."""
        # Given: 기본 DTO 및 상세 API 응답
        dto = NoticeDTO(notice_id='001', title='테스트', org_name='기관', notice_type='유형', raw_data={})
        detail_data = {'bscAmt': '1000000', 'dmndComp': '수요기관'}

        # When: 정보 보강 실행
        enriched = transformer.enrich_with_detail(dto, detail_data)

        # Then: 보강된 필드 값 및 원본 데이터 업데이트 확인
        assert enriched.budget == '1000000'
        assert enriched.demand_company == '수요기관'
        assert 'detail' in enriched.raw_data

    def test_validate_notice_dto_success(self):
        """모든 필수 값이 채워진 DTO가 검증을 통과하는지 확인합니다."""
        dto = NoticeDTO(notice_id='20240001', title='정상 공고', org_name='기관', notice_type='유형')
        validate_notice_dto(dto)  # 에러가 발생하지 않아야 함

    def test_validate_notice_dto_missing_id(self):
        """식별자가 비어있는 DTO는 검증 에러(ValidationError)를 발생시키는지 확인합니다."""
        dto = NoticeDTO(notice_id='', title='공고', org_name='기관', notice_type='유형')
        with pytest.raises(ValidationError):
            validate_notice_dto(dto)

    def test_validate_notice_dto_invalid_title(self):
        """의미 없는 제목(제목없음)을 가진 데이터는 검증에서 탈락시키는지 확인합니다."""
        dto = NoticeDTO(notice_id='20240001', title='제목없음', org_name='기관', notice_type='유형')
        with pytest.raises(ValidationError):
            validate_notice_dto(dto)


class TestCrawlerConfig:
    """설정 객체 테스트: 크롤러 작동 파라미터의 유효성 검사 로직을 검증합니다."""

    def test_config_creation_success(self):
        """정상적인 범위 내의 설정값이 올바르게 할당되는지 확인합니다."""
        config = CrawlerConfig(max_pages=5, records_per_page=20, fetch_details=True)
        assert config.max_pages == 5
        assert config.records_per_page == 20

    def test_config_invalid_max_pages(self):
        """비정상적인 페이지 수(0 이하) 입력 시 예외를 발생시키는지 확인합니다."""
        with pytest.raises(ValueError):
            CrawlerConfig(max_pages=0)

    def test_config_invalid_records_per_page(self):
        """페이지당 건수가 허용 범위를 벗어날 경우 예외를 발생시키는지 확인합니다."""
        with pytest.raises(ValueError):
            CrawlerConfig(records_per_page=0)
        with pytest.raises(ValueError):
            CrawlerConfig(records_per_page=101)


class TestCrawlerStats:
    """통계 객체 테스트: 수집 진행 상황 및 결과 집계 로직을 검증합니다."""

    def test_stats_initialization(self):
        """통계 카운터가 0으로 정상 초기화되는지 확인합니다."""
        stats = CrawlerStats()
        assert stats.total_found == 0
        assert stats.total_collected == 0

    def test_stats_to_dict(self):
        """통계 결과가 DB 저장 또는 API 응답을 위한 딕셔너리로 정확히 변환되는지 확인합니다."""
        stats = CrawlerStats(total_found=10, total_collected=8, total_skipped=2)
        result = stats.to_dict()
        assert result['total_found'] == 10
        assert result['total_collected'] == 8


class TestNuriCrawler:
    """오케스트레이션 계층 테스트: 계층 간 상호작용 및 전체 수집 워크플로우를 검증합니다."""

    @pytest.fixture
    def mock_client(self): return Mock(spec=NuriAPIClient)

    @pytest.fixture
    def mock_transformer(self): return Mock(spec=NuriDataTransformer)

    @pytest.fixture
    def mock_storage(self):
        """저장소 상태를 시뮬레이션하기 위한 Mock 객체를 설정합니다."""
        storage = Mock(spec=CrawlerStorage)
        storage.is_already_done.return_value = False
        storage.get_count.return_value = 0
        storage.start_session.return_value = 1
        return storage

    def test_crawler_initialization(self, mock_client, mock_transformer, mock_storage):
        """의존성 주입을 통해 각 계층의 부품들이 올바르게 조립되는지 확인합니다."""
        crawler = NuriCrawler(client=mock_client, transformer=mock_transformer, storage=mock_storage)
        assert crawler.client is mock_client
        assert crawler.storage is mock_storage

    def test_crawler_run_success(self, mock_client, mock_transformer, mock_storage):
        """전체 크롤링 루프가 에러 없이 시작부터 종료(세션 관리 포함)까지 완료되는지 확인합니다."""
        # Given: 데이터가 없는 정상 상황 모사
        mock_client.fetch_notice_list.return_value = {'result': []}
        mock_transformer.extract_notices.return_value = []
        crawler = NuriCrawler(client=mock_client, transformer=mock_transformer, storage=mock_storage)

        # When: 크롤러 실행
        results = crawler.run(max_pages=1, records_per_page=5)

        # Then: 세션 시작/종료 함수가 호출되었는지 검증
        assert isinstance(results, list)
        mock_storage.start_session.assert_called_once()
        mock_storage.finish_session.assert_called_once()

    def test_crawler_process_notice(self, mock_client, mock_transformer, mock_storage):
        """단일 공고가 발견되었을 때 변환 -> 저장 프로세스가 정상 호출되는지 확인합니다."""
        # Given: 1건의 공고 발견 시나리오
        raw_notice = {'bidPbancNo': '001', 'bidPbancNm': '공고'}
        dto = NoticeDTO(notice_id='001', title='공고', org_name='기관', notice_type='유형')

        mock_client.fetch_notice_list.return_value = {'result': [raw_notice]}
        mock_transformer.extract_notices.return_value = [raw_notice]
        mock_transformer.transform_notice.return_value = dto

        crawler = NuriCrawler(client=mock_client, transformer=mock_transformer, storage=mock_storage)

        # When: 실행
        results = crawler.run(max_pages=1)

        # Then: 결과 리스트에 추가되고 DB 저장이 호출되었는지 확인
        assert len(results) == 1
        mock_storage.save_notice.assert_called_once()

    def test_crawler_skip_duplicate(self, mock_client, mock_transformer, mock_storage):
        """이미 수집된 중복 공고의 경우 저장 로직을 건너뛰는지(증분 수집) 확인합니다."""
        # Given: 이미 DB에 있는 공고 ID 시뮬레이션
        raw_notice = {'bidPbancNo': '001'}
        dto = NoticeDTO(notice_id='001', title='공고', org_name='기관', notice_type='유형')

        mock_client.fetch_notice_list.return_value = {'result': [raw_notice]}
        mock_transformer.extract_notices.return_value = [raw_notice]
        mock_transformer.transform_notice.return_value = dto
        mock_storage.is_already_done.return_value = True  # 중복 상태 설정

        crawler = NuriCrawler(client=mock_client, transformer=mock_transformer, storage=mock_storage)

        # When: 실행
        results = crawler.run(max_pages=1)

        # Then: 결과는 비어있어야 하며 저장이 수행되지 않아야 함
        assert len(results) == 0
        mock_storage.save_notice.assert_not_called()

    def test_crawler_context_manager(self, mock_client, mock_transformer, mock_storage):
        """with 문(Context Manager) 종료 시 리소스(세션, DB)를 안전하게 닫는지 확인합니다."""
        # When
        with NuriCrawler(client=mock_client, transformer=mock_transformer, storage=mock_storage) as crawler:
            assert crawler is not None

        # Then: 명시적으로 close 메서드들이 호출되었는지 검증
        mock_client.close.assert_called_once()
        mock_storage.close.assert_called_once()


class TestCrawlerIntegration:
    """통합 테스트: 실제 SQLite(인메모리)를 사용하여 계층 간 데이터 흐름을 최종 확인합니다."""

    @pytest.mark.asyncio
    async def test_full_integration_with_memory_db(self):
        """Mock 클라이언트와 실제 Storage/Transformer가 협력하여 DB 저장까지 완료하는지 테스트합니다."""
        # Given: 실제 구성 요소와 메모리 DB 준비
        mock_client = Mock(spec=NuriAPIClient)
        mock_client.fetch_notice_list.return_value = {
            'result': [{'bidPbancNo': 'TEST-001', 'bidPbancNm': '테스트 공고', 'grpNm': '기관', 'prcmBsneSeCdNm': '물품'}]
        }
        storage = CrawlerStorage(db_path=":memory:")
        transformer = NuriDataTransformer()
        crawler = NuriCrawler(client=mock_client, transformer=transformer, storage=storage)

        # When: 실행
        results = crawler.run(max_pages=1)

        # Then: DB 레코드 건수 및 중복 체크 기능 정상 작동 확인
        assert len(results) == 1
        assert storage.get_count() == 1
        assert storage.is_already_done('TEST-001') is True

        crawler.close()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])