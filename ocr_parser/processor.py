import re
import csv
import time
from pathlib import Path
from typing import List
from loguru import logger
from ocr_parser.schemas import WeightTicket, ParsingResult

# 글로벌 설정 및 임계값 정의
MIN_WEIGHT_KG = 100
MAX_WEIGHT_KG = 999_999
DEFAULT_OUTPUT_DIR = "output"


class WeightTicketParser:
    """
    계근표 OCR 텍스트에서 차량번호 및 중량 데이터를 추출하는 파싱 엔진입니다.
    정규표현식 기반의 라벨 매칭과 중량값 자동 보정 로직을 포함합니다.
    """

    def __init__(self, output_dir: str = DEFAULT_OUTPUT_DIR):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # 파싱에 사용될 정규식 라벨 정의
        self.labels = {
            'vehicle_number': r"(?:차량\s*번호|차\s*번호|차\s*번|차량\s*No\.?)",
            'gross_weight': r"(?:총\s*중\s*량|Gross|중\s*량|총중량|품종명랑)",
            'tare_weight': r"(?:공차\s*중\s*량|Tare|차\s*중\s*량|공차중량|차중량)",
            'net_weight': r"(?:실\s*중\s*량|Net|실중량)",
            'ticket_number': r"(?:계근(?:표|지)?번호|전표번호|날\s*짜|ID-NO|계량횟수|계량일자)"
        }

    def _clean_text(self, text: str) -> str:
        """
        중량 오인식을 방지하기 위해 시간 데이터 및 숫자 간 공백을 제거합니다.
        예: '11시 30분' 제거, '14 080' -> '14080' 통합
        """
        # 시간 형식 노이즈 제거 (시/분 및 콜론 기준)
        text = re.sub(r"\d{1,2}시\s*\d{1,2}분", " ", text)
        text = re.sub(r"\d{1,2}\s*[:：]\s*\d{2}(?:\s*[:：]\s*\d{2})?", " ", text)
        # 천단위 공백 발생 시 숫자 통합
        text = re.sub(r"(\d)\s+(\d{3})", r"\1\2", text)
        return text

    def _extract_weight(self, label_pattern: str, text: str) -> int:
        """
        특정 라벨 뒤에 등장하는 중량(kg)을 추출합니다.
        단위가 없더라도 유효 중량 범위 내 숫자를 탐색합니다.
        """
        cleaned = self._clean_text(text)

        # 1순위: 라벨 뒤 '숫자 + kg' 패턴 탐색
        pattern = label_pattern + r"[\s\S]{0,100}?(\d[\d,]{2,})\s*kg"
        matches = re.findall(pattern, cleaned)

        weights = [int(m.replace(",", "")) for m in matches
                   if MIN_WEIGHT_KG <= int(m.replace(",", "")) <= MAX_WEIGHT_KG]

        # 2순위: 'kg' 단위가 없는 경우 숫자만 탐색
        if not weights:
            pattern2 = label_pattern + r"\s*[:：]?\s*(\d[\d,]{2,})\b"
            matches2 = re.findall(pattern2, cleaned)
            weights = [int(m.replace(",", "")) for m in matches2
                       if MIN_WEIGHT_KG <= int(m.replace(",", "")) <= MAX_WEIGHT_KG]

        return weights[0] if weights else 0

    def parse(self, text: str) -> ParsingResult:
        """
        전체 텍스트를 분석하여 WeightTicket 객체를 생성합니다.
        중량값 누락 시 산술 관계(총중량-공차=실중량)를 이용하여 보정합니다.
        """
        start_time = time.time()
        cleaned_text = self._clean_text(text)
        extracted = {}

        try:
            # 1. 차량번호 추출 (한국 번호판 형식 대응)
            v_match = re.search(
                self.labels['vehicle_number'] + r"\s*[:\s：]*((?:[가-힣]*\s*)?[\d\sA-Z]{2,3}[가-힣][\d\s]{4}|[\d]{4})",
                cleaned_text)
            extracted['vehicle_number'] = v_match.group(1).replace(" ", "") if v_match else "UNKNOWN"

            # 2. 전표번호 추출
            t_match = re.search(self.labels['ticket_number'] + r"\s*[:\s：]*([A-Z0-9-]+)", cleaned_text)
            extracted['ticket_number'] = t_match.group(1) if t_match else "0000"

            # 3. 각 항목별 중량 추출
            extracted['gross_weight'] = self._extract_weight(self.labels['gross_weight'], text)
            extracted['tare_weight'] = self._extract_weight(self.labels['tare_weight'], text)
            extracted['net_weight'] = self._extract_weight(self.labels['net_weight'], text)

            # 4. 데이터 보정 로직
            non_zero = [w for w in [extracted['gross_weight'], extracted['tare_weight'], extracted['net_weight']] if
                        w > 0]

            # 세 값이 모두 있을 경우 크기순 정렬 (OCR 오인식 보정)
            if len(non_zero) >= 3:
                all_w = sorted(non_zero, reverse=True)
                extracted['gross_weight'], extracted['tare_weight'], extracted['net_weight'] = all_w[0], all_w[1], \
                all_w[2]

            # 두 값만 있을 경우 나머지 하나 계산
            elif len(non_zero) == 2:
                if extracted['gross_weight'] > 0 and extracted['net_weight'] > 0 and extracted['tare_weight'] == 0:
                    extracted['tare_weight'] = extracted['gross_weight'] - extracted['net_weight']
                elif extracted['gross_weight'] > 0 and extracted['tare_weight'] > 0 and extracted['net_weight'] == 0:
                    extracted['net_weight'] = extracted['gross_weight'] - extracted['tare_weight']
                elif extracted['tare_weight'] > 0 and extracted['net_weight'] > 0 and extracted['gross_weight'] == 0:
                    extracted['gross_weight'] = extracted['tare_weight'] + extracted['net_weight']

            # Pydantic 모델을 통한 최종 검증
            ticket = WeightTicket(**extracted)
            return ParsingResult(
                success=True,
                data=ticket,
                processing_time_ms=(time.time() - start_time) * 1000
            )

        except Exception as e:
            logger.error(f"파싱 중 예외 발생: {e}")
            return ParsingResult(
                success=False,
                error_message=str(e),
                processing_time_ms=(time.time() - start_time) * 1000
            )

    def save_csv(self, results: List[ParsingResult], filename: str) -> Path:
        """분석 결과 리스트를 UTF-8-BOM 형식의 CSV로 저장합니다."""
        filepath = self.output_dir / filename
        success_data = [r.data.model_dump() for r in results if r.success and r.data]

        if not success_data:
            logger.warning("저장할 성공 데이터가 없습니다.")
            return filepath

        with open(filepath, 'w', encoding='utf-8-sig', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=success_data[0].keys())
            writer.writeheader()
            writer.writerows(success_data)

        logger.info(f"결과 저장 완료: {filepath}")
        return filepath