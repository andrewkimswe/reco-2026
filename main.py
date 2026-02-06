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

# 로깅 설정 (깔끔하게 한 줄로 출력)
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
        logger.info(f"'{sample_dir}' 폴더를 생성하고 JSON 파일을 넣어주세요.")
        return

    # JSON 파일 목록 가져오기
    json_files = list(sample_dir.glob("*.json"))

    if not json_files:
        logger.warning(f"'{sample_dir}' 폴더에 JSON 파일이 없습니다.")
        logger.info("테스트를 위해 샘플 데이터를 생성합니다...")
        _create_sample_data(sample_dir)
        json_files = list(sample_dir.glob("*.json"))

    results = []
    logger.info(f"총 {len(json_files)}개의 파일을 처리합니다.\n")

    for idx, json_file in enumerate(json_files, 1):
        try:
            logger.info(f"[{idx}/{len(json_files)}] 파일 처리 중: {json_file.name}")

            with open(json_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                ocr_text = data.get('text', '')

                if not ocr_text:
                    logger.warning(f"  └─ 텍스트 데이터가 비어있습니다.")
                    continue

                # 파싱 실행
                result = parser.parse(ocr_text)

                if result.success and result.data:
                    results.append(result)
                    logger.success(
                        f"  └─ 성공: 차량번호={result.data.vehicle_number}, "
                        f"총중량={result.data.gross_weight}kg, "
                        f"실중량={result.data.net_weight}kg"
                    )
                else:
                    logger.error(f"  └─ 실패: {result.error_message}")

        except json.JSONDecodeError as e:
            logger.error(f"  └─ JSON 파싱 오류: {e}")
        except Exception as e:
            logger.error(f"  └─ 파일 처리 오류: {e}")

    # 결과 저장
    logger.info("")
    if results:
        output_file = parser.save_csv(results, "ocr_results.csv")
        logger.success(f"✓ {len(results)}건의 데이터를 CSV로 저장했습니다: {output_file}")
    else:
        logger.warning("저장할 성공 데이터가 없습니다.")

    logger.info("=" * 60)


def run_crawler_task(pages: int, fetch_details: bool):
    """[Task B] 누리장터 수집 실행"""
    logger.info("=" * 60)
    logger.info("과제 B: 누리장터 데이터 수집 시작")
    logger.info(f"설정: {pages}페이지, 상세조회={'ON' if fetch_details else 'OFF'}")
    logger.info("=" * 60)

    config = CrawlerConfig(
        max_pages=pages,
        fetch_details=fetch_details,
        records_per_page=10
    )

    try:
        with NuriCrawler() as crawler:
            # 수집 실행
            notices = crawler.run_with_config(config)

            # CSV 내보내기
            logger.info("\n데이터 내보내기 중...")
            crawler.export_csv("output/nuri_notices.csv")
            crawler.export_json("output/nuri_notices.json")

            logger.success(f"✓ 누리장터 수집 완료: 총 {len(notices)}건")

    except Exception as e:
        logger.error(f"크롤링 중 오류 발생: {e}")
        raise

    logger.info("=" * 60)


def _create_sample_data(sample_dir: Path):
    """테스트용 샘플 JSON 데이터 생성"""
    sample_dir.mkdir(parents=True, exist_ok=True)

    samples = [
        {
            "filename": "sample_1.json",
            "text": """
            계근표번호: T-2024-001
            차량번호: 12가3456
            총중량: 14,080 kg
            공차중량: 8,500 kg
            실중량: 5,580 kg
            날짜: 2024-01-15
            """
        },
        {
            "filename": "sample_2.json",
            "text": """
            전표번호: T-2024-002
            차 번호: 서울78나9012
            Gross: 18500kg
            Tare: 9200kg
            Net: 9300kg
            """
        }
    ]

    for sample in samples:
        filepath = sample_dir / sample["filename"]
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump({"text": sample["text"]}, f, ensure_ascii=False, indent=2)

    logger.info(f"샘플 파일 {len(samples)}개를 생성했습니다.")


def main():
    """메인 엔트리 포인트"""
    parser = argparse.ArgumentParser(
        description="OCR 파싱 및 누리장터 크롤링 통합 실행 도구",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
사용 예시:
  python main.py ocr                    # OCR만 실행
  python main.py crawler --pages 3      # 크롤러만 실행 (3페이지)
  python main.py crawler --pages 5 --details  # 상세정보 포함
  python main.py all --pages 2          # 둘 다 실행
        """
    )

    parser.add_argument(
        "task",
        choices=["ocr", "crawler", "all"],
        help="실행할 작업 선택 (ocr: OCR 파싱, crawler: 누리장터 수집, all: 모두 실행)"
    )
    parser.add_argument(
        "--pages",
        type=int,
        default=1,
        help="크롤러 수집 페이지 수 (기본값: 1)"
    )
    parser.add_argument(
        "--details",
        action="store_true",
        help="크롤러 실행 시 상세정보까지 수집 (추가 API 호출)"
    )

    args = parser.parse_args()

    # 필수 폴더 자동 생성
    for directory in ["output", "logs", "data", "samples"]:
        Path(directory).mkdir(parents=True, exist_ok=True)

    try:
        # 작업 분기 처리
        if args.task == "ocr":
            run_ocr_task()

        elif args.task == "crawler":
            run_crawler_task(args.pages, args.details)

        elif args.task == "all":
            # 둘 다 실행
            run_ocr_task()
            logger.info("\n")  # 구분선
            run_crawler_task(args.pages, args.details)

        logger.success("\n✓ 모든 작업이 완료되었습니다!")

    except KeyboardInterrupt:
        logger.warning("\n사용자에 의해 중단되었습니다.")
        sys.exit(0)
    except Exception as e:
        logger.exception(f"치명적 오류 발생: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()