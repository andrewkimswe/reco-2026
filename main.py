import argparse
import asyncio
import sys
import os
import json
from pathlib import Path
from loguru import logger

# 모듈 임포트
from ocr_parser.processor import WeightTicketParser
from crawler.crawler import NuriCrawler, CrawlerConfig

# 로깅 설정: 시간 | 레벨 | 메시지만 깔끔하게 출력
logger.remove()
logger.add(
    sys.stderr,
    format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>"
)


def run_ocr_task():
    """[Task A] OCR 파싱 실행 - samples 폴더의 모든 JSON 파일 처리"""
    logger.info("=" * 60)
    logger.info("과제 A: OCR 계근표 파싱 시작")
    logger.info("=" * 60)

    parser = WeightTicketParser()
    sample_dir = Path("samples")

    if not sample_dir.exists():
        logger.error(f"'{sample_dir}' 폴더가 존재하지 않습니다.")
        return

    json_files = list(sample_dir.glob("*.json"))
    if not json_files:
        logger.warning(f"'{sample_dir}' 폴더에 처리할 JSON 파일이 없습니다.")
        return

    results = []
    for idx, json_file in enumerate(json_files, 1):
        try:
            with open(json_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                ocr_text = data.get('text', '')
                if not ocr_text: continue

                result = parser.parse(ocr_text)
                if result.success and result.data:
                    results.append(result)
                    logger.success(f"[{idx}] {json_file.name} 파싱 성공: {result.data.vehicle_number}")
                else:
                    logger.error(f"[{idx}] {json_file.name} 실패: {result.error_message}")
        except Exception as e:
            logger.error(f"파일 처리 오류 ({json_file.name}): {e}")

    if results:
        output_file = parser.save_csv(results, "ocr_results.csv")
        logger.info(f"결과 저장 완료: {output_file}")
    logger.info("=" * 60)


async def start_crawling(config: CrawlerConfig):
    """실제 크롤링 엔진 실행 및 내보내기"""
    try:
        with NuriCrawler() as crawler:
            notices = crawler.run_with_config(config)
            crawler.export_csv("output/nuri_notices.csv")
            logger.success(f"수집 완료: 총 {len(notices)}건")
            return len(notices)
    except Exception as e:
        logger.error(f"크롤링 실행 중 에러: {e}")
        return 0


async def run_crawler_task(mode: str, interval: int, pages: int, fetch_details: bool):
    """[Task B] 누리장터 수집 실행 (Interval/Once 모드 지원)"""
    logger.info("=" * 60)
    logger.info(f"과제 B: 누리장터 데이터 수집 시작 (모드: {mode})")
    logger.info("=" * 60)

    config = CrawlerConfig(
        max_pages=pages,
        fetch_details=fetch_details,
        records_per_page=10
    )

    if mode == "once":
        # Cron 및 외부 스케줄러용 1회 실행 모드
        await start_crawling(config)
    else:
        # 상주 실행형 내장 스케줄러 모드
        logger.info(f"내장 스케줄러 활성화: {interval}초 간격으로 반복 실행합니다.")
        while True:
            await start_crawling(config)
            logger.info(f"{interval}초 대기 중... (중단: Ctrl+C)")
            await asyncio.sleep(interval)


async def main():
    """메인 엔트리 포인트"""
    parser = argparse.ArgumentParser(description="OCR 및 누리장터 크롤링 통합 도구")

    # 필수 작업 선택
    parser.add_argument("task", choices=["ocr", "crawler", "all"], help="실행할 작업")

    # 실행 모드 및 옵션
    parser.add_argument("--mode", choices=["once", "interval"], default="once", help="실행 모드 (기본: once)")
    parser.add_argument("--seconds", type=int, default=3600, help="interval 모드 시 대기 시간(초)")
    parser.add_argument("--pages", type=int, default=1, help="수집 페이지 수")
    parser.add_argument("--details", action="store_true", help="상세정보 수집 활성화")

    args = parser.parse_args()

    # 필수 폴더 생성
    for d in ["output", "logs", "data", "samples"]:
        Path(d).mkdir(parents=True, exist_ok=True)

    try:
        if args.task == "ocr":
            run_ocr_task()
        elif args.task == "crawler":
            await run_crawler_task(args.mode, args.seconds, args.pages, args.details)
        elif args.task == "all":
            run_ocr_task()
            print("\n")  # 시각적 구분
            await run_crawler_task(args.mode, args.seconds, args.pages, args.details)

        logger.success("\n✓ 모든 지정 작업이 완료되었습니다.")

    except KeyboardInterrupt:
        logger.warning("\n사용자에 의해 중단되었습니다.")
        sys.exit(0)


if __name__ == "__main__":
    asyncio.run(main())