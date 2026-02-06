import os
import sys
import json
import pytest

# 프로젝트 루트 경로를 sys.path에 추가하여 패키지 임포트 문제를 해결합니다.
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from ocr_parser.processor import WeightTicketParser


@pytest.fixture
def parser():
    """테스트마다 독립적인 파서 인스턴스를 생성합니다."""
    return WeightTicketParser()


def get_sample_text(file_name):
    """
    JSON 샘플 파일에서 OCR 결과 텍스트를 읽어옵니다.
    파일이 없을 경우 테스트를 실패시키지 않고 건너뜁니다.
    """
    path = os.path.join(BASE_DIR, "samples", file_name)
    if not os.path.exists(path):
        pytest.skip(f"샘플 파일을 찾을 수 없음: {file_name}")
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f).get('text', '')


@pytest.mark.parametrize("file_name, expected_v, min_gross", [
    ("sample_01.json", "8713", 12000),
    ("sample_02.json", "80구8713", 13000),
    ("sample_03.json", "5405", 14000),
    ("sample_04.json", "0580", 14000),
])
def test_json_samples(parser, file_name, expected_v, min_gross):
    """
    실제 OCR 결과 샘플들을 대상으로 파싱 정확도를 검증합니다.
    - 차량번호 추출 성공 여부
    - 시간 데이터와 중량 데이터의 혼동 방지
    - 총중량-공차중량-실중량의 산술적 무결성
    """
    text = get_sample_text(file_name)
    result = parser.parse(text)

    # 1. 파싱 프로세스 자체의 성공 여부 확인
    assert result.success is True

    # 2. 차량번호 정규화 결과 확인
    assert result.data.vehicle_number == expected_v

    # 3. 중량 데이터 임계값 검증 (시간 데이터 '02', '11' 등을 중량으로 오인했는지 체크)
    assert result.data.gross_weight >= min_gross

    # 4. Pydantic 스키마 내 비즈니스 로직(오차 검증) 통과 여부 확인
    assert result.data.is_weight_valid is True, f"{file_name}에서 중량 산술 불일치 발생"


def test_csv_excel_compatibility(parser):
    """
    저장된 CSV 파일이 엑셀에서 한글 깨짐 없이 열리는지 확인합니다.
    UTF-8-BOM(Byte Order Mark) 서명 존재 여부를 검증합니다.
    """
    # 가상의 OCR 결과 데이터 생성
    text = "차량번호: 12가3456\n총중량: 25000kg\n공차중량: 10000kg\n실중량: 15000kg\n계근표: T-001"
    result = parser.parse(text)

    # CSV 저장 수행
    filepath = parser.save_csv([result], "test_bom.csv")

    # 바이너리 모드로 읽어 파일 시작 부분의 BOM(\xef\xbb\xbf) 확인
    with open(filepath, 'rb') as f:
        assert f.read(3) == b'\xef\xbb\xbf'