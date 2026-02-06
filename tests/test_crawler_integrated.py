"""
누리장터 크롤러 통합 테스트 (Integration Test)
- 목적: 계층 분리(Client, Transformer, Storage) 후 전체 시스템의 유기적 작동을 검증합니다.
- 특징: Mock이 아닌 실제 API와 인메모리 DB를 사용하여 End-to-End 흐름을 테스트합니다.
- 검증 항목: 하위 호환성, 증분 수집(중복 제거), 상세 정보 연동, 데이터 내보내기 등.
"""

import pytest
from crawler.crawler import NuriCrawler, create_crawler


@pytest.mark.asyncio
async def test_full_logic_integration_with_new_architecture():
    """
    [핵심 로직 통합] 새로운 DTO 기반 아키텍처가 실제 API와 DB 사이에서 정상 작동하는지 확인합니다.
    """
    # 1. 테스트용 휘발성 메모리 DB 초기화
    crawler = create_crawler(db_path=":memory:")

    try:
        # 2. 크롤링 수행 (실제 네트워크 통신 발생)
        results = crawler.run(
            max_pages=1,
            records_per_page=5,
            fetch_details=False
        )

        # 3. 데이터 영속성(Persistence) 검증: DB에 성공적으로 저장되었는가?
        count = crawler.storage.get_count()
        assert count > 0, "데이터가 DB에 저장되지 않았습니다."

        # 4. 중복 방지 로직 검증: 수집된 직후 '이미 수집됨' 상태로 전이되었는가?
        if results:
            first_id = results[0].notice_id  # DTO 객체 속성 접근 방식 검증
            assert crawler.storage.is_already_done(first_id) is True
            print(f"\n 신규 아키텍처 통합 성공: {count}건 수집 및 데이터 무결성 확인")

        # 5. 타입 안정성 검증: 반환된 객체가 표준 DTO 규격을 준수하는가?
        assert all(hasattr(r, 'notice_id') for r in results), "결과 데이터가 DTO 객체 형식이 아닙니다."

    finally:
        crawler.close()


@pytest.mark.asyncio
async def test_backward_compatibility():
    """
    [하위 호환성] 아키텍처 변경 후에도 기존 코드(Legacy)의 호출 방식이 유효한지 검증합니다.
    """
    # 기존 방식의 생성자 호출이 여전히 유효한지 확인
    crawler = NuriCrawler(db_path=":memory:")

    try:
        # 기존과 동일한 인터페이스(run 메서드) 작동 여부 확인
        results = crawler.run(
            max_pages=1,
            records_per_page=5,
            fetch_details=False
        )

        assert isinstance(results, list), "결과값은 리스트 형태여야 합니다."

        # 외부 모듈에서 직접 접근하던 속성(storage 등)의 존재 여부 확인
        assert hasattr(crawler, 'storage'), "외부 접근을 위한 storage 속성이 누락되었습니다."
        assert hasattr(crawler.storage, 'get_count'), "storage 내부 메서드 접근이 불가능합니다."

        print(f"\n 하위 호환성 검증 완료: 기존 인터페이스 안정성 확보")

    finally:
        crawler.close()


@pytest.mark.asyncio
async def test_incremental_crawling():
    """
    [증분 크롤링] 멱등성(Idempotency) 검증: 동일한 데이터를 반복 수집해도 DB 중복이 발생하지 않아야 합니다.
    """
    crawler = create_crawler(db_path=":memory:")

    try:
        # 1차 수집 수행
        results1 = crawler.run(max_pages=1, records_per_page=5)
        count1 = crawler.storage.get_count()

        # 2차 수집 수행 (동일 대상)
        results2 = crawler.run(max_pages=1, records_per_page=5)
        count2 = crawler.storage.get_count()

        # 검증: DB 건수는 유지되어야 하며, 결과 리스트는 비어있어야 함(Skip 처리)
        assert count1 == count2, "중복 데이터가 DB에 삽입되었습니다."
        assert len(results2) == 0, "이미 수집된 데이터는 결과 리스트에서 제외되어야 합니다."

        print(f"\n 증분 수집 확인: 1차 {count1}건 수집, 2차 중복 제거 성공")

    finally:
        crawler.close()


@pytest.mark.asyncio
async def test_with_detail_fetching():
    """
    [상세 정보 연동] 목록 조회 후 상세 API를 추가 호출하여 데이터를 보강하는 흐름을 검증합니다.
    """
    crawler = create_crawler(db_path=":memory:")

    try:
        # fetch_details 옵션을 활성화하여 수집
        results = crawler.run(
            max_pages=1,
            records_per_page=3,
            fetch_details=True
        )

        assert len(results) > 0, "데이터 수집에 실패했습니다."

        # 보강된 데이터(raw_data 내 detail 키)가 실제로 존재하는지 확인
        detail_verified = False
        for result in results:
            if result.raw_data and 'detail' in result.raw_data:
                detail_verified = True
                print(f" 상세 데이터 보강 확인: {result.notice_id}")
                break

        assert detail_verified, "상세 정보 보강 로직이 작동하지 않았습니다."

    finally:
        crawler.close()


@pytest.mark.asyncio
async def test_export_functionality():
    """
    [데이터 내보내기] 수집된 DB 데이터를 외부 파일(JSON, CSV)로 올바르게 추출하는지 검증합니다.
    """
    import tempfile
    import os

    crawler = create_crawler(db_path=":memory:")

    try:
        # 데이터 수집
        results = crawler.run(max_pages=1, records_per_page=5)

        if results:
            with tempfile.TemporaryDirectory() as tmpdir:
                json_path = os.path.join(tmpdir, "test_notices.json")
                csv_path = os.path.join(tmpdir, "test_notices.csv")

                # JSON 추출 및 파일 존재 여부 확인
                crawler.export_json(json_path)
                assert os.path.exists(json_path), "JSON 파일 생성 실패"

                # CSV 추출 및 파일 존재 여부 확인
                crawler.export_csv(csv_path)
                assert os.path.exists(csv_path), "CSV 파일 생성 실패"

                print(f"\n 파일 내보내기 확인: JSON/CSV 포맷 정상 추출")

    finally:
        crawler.close()


@pytest.mark.asyncio
async def test_statistics():
    """
    [운영 통계] 수집 작업 결과(발견, 성공, 건너뜀)가 정확하게 집계되는지 확인합니다.
    """
    crawler = create_crawler(db_path=":memory:")

    try:
        crawler.run(max_pages=2, records_per_page=5)

        # 통계 객체 획득
        stats = crawler.get_stats()

        # 필수 통계 지표 존재 여부 확인
        required_keys = ['total_found', 'total_collected', 'total_skipped', 'total_notices']
        assert all(key in stats for key in required_keys), "필수 통계 지표가 누락되었습니다."

        print(f"\n 통계 지표 확인: 발견({stats['total_found']}) / 저장({stats['total_notices']})")

    finally:
        crawler.close()


@pytest.mark.asyncio
async def test_context_manager_usage():
    """
    [리소스 관리] Context Manager(with 문) 사용 시 세션 및 DB 연결이 자동 해제되는지 확인합니다.
    """
    # RAII 패턴: 진입 시 생성, 종료 시 자동 close() 호출
    with create_crawler(db_path=":memory:") as crawler:
        results = crawler.run(max_pages=1, records_per_page=5)
        count = crawler.storage.get_count()
        assert count > 0
        print(f"\n Context Manager 연동 확인: {count}건 안전 수집")

    print(" 리소스 라이프사이클 관리: 자동 종료 완료")


@pytest.mark.asyncio
async def test_error_resilience():
    """
    [장애 복원력] 일부 요청 실패나 데이터 오류 시에도 전체 수집 프로세스가 중단되지 않는지 검증합니다.
    """
    crawler = create_crawler(db_path=":memory:")

    try:
        # 다중 페이지 크롤링 시 개별 페이지 에러에 대한 내성 테스트
        results = crawler.run(max_pages=3, records_per_page=5)
        stats = crawler.get_stats()

        print(f"\n 결함 허용(Fault Tolerance) 확인:")
        print(f"   성공 페이지: {stats.get('pages_processed', 0)}")
        print(f"   실패 페이지: {stats.get('pages_failed', 0)}")

        # 최소한 프로세스가 끝까지 완주했는지가 핵심
        assert 'total_collected' in stats

    finally:
        crawler.close()


if __name__ == "__main__":
    import asyncio

    print("\n" + "=" * 60)
    print("JoyLab 누리장터 크롤러: 아키텍처 통합 테스트 실행")
    print("=" * 60)

    async def run_all_tests():
        # 순차적으로 모든 시나리오 검증 실행
        tests = [
            ("전체 로직 통합", test_full_logic_integration_with_new_architecture),
            ("하위 호환성", test_backward_compatibility),
            ("증분 크롤링", test_incremental_crawling),
            ("상세 정보 연동", test_with_detail_fetching),
            ("파일 내보내기", test_export_functionality),
            ("운영 통계 집계", test_statistics),
            ("컨텍스트 매니저", test_context_manager_usage),
            ("에러 복원력", test_error_resilience),
        ]

        for name, test_func in tests:
            print(f"\n▶ [{name}] 테스트 시작...")
            await test_func()

        print("\n" + "=" * 60)
        print(" 모든 통합 테스트 시나리오 통과!")
        print("=" * 60)

    asyncio.run(run_all_tests())