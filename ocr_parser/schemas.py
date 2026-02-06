from datetime import datetime
from typing import Optional, Any
from pydantic import BaseModel, Field, field_validator, model_validator
from loguru import logger

# 운영 요구사항에 따른 물리적 오차 허용 범위 (단위: kg)
WEIGHT_TOLERANCE_KG = 10


class WeightTicket(BaseModel):
    """
    계근표의 핵심 데이터를 정의하는 스키마입니다.
    Pydantic을 통해 타입 검증과 비즈니스 로직(중량 산술 검증)을 동시에 수행합니다.
    """
    ticket_number: str = Field(..., description="전표 일련번호")
    vehicle_number: str = Field(..., description="차량 번호")
    gross_weight: int = Field(..., ge=0, description="총중량 (차량 + 적재물)")
    tare_weight: int = Field(..., ge=0, description="공차중량 (빈 차량 무게)")
    net_weight: int = Field(..., ge=0, description="실중량 (순수 적재물 무게)")
    parsed_at: datetime = Field(default_factory=datetime.now, description="파싱 수행 시각")
    is_weight_valid: bool = Field(True, description="산술 검증 통과 여부")

    @field_validator('vehicle_number', 'ticket_number', mode='before')
    @classmethod
    def normalize_strings(cls, v: Any) -> str:
        """
        OCR 인식 과정에서 발생할 수 있는 앞뒤 공백을 제거하고,
        영어 알파벳을 대문자로 통일하여 데이터 일관성을 유지합니다.
        """
        if isinstance(v, str):
            return v.strip().upper()
        return str(v)

    @model_validator(mode='after')
    def validate_weight_calculation(self) -> 'WeightTicket':
        """
        [비즈니스 로직] 총중량 - 공차중량 = 실중량 관계를 검증합니다.
        OCR 오인식으로 인해 오차가 발생할 경우 로그를 남기고 유효성 플래그를 변경합니다.
        """
        # 기대되는 실중량 계산
        expected_net = abs(self.gross_weight - self.tare_weight)

        # 실제 OCR 값과 계산값의 차이 측정
        diff = abs(self.net_weight - expected_net)

        if diff > WEIGHT_TOLERANCE_KG:
            self.is_weight_valid = False
            logger.warning(
                f"[검증 실패] 전표번호: {self.ticket_number} | "
                f"오차 발생: {diff}kg (허용범위: {WEIGHT_TOLERANCE_KG}kg) | "
                f"상세: 계산({expected_net}kg) vs OCR({self.net_weight}kg)"
            )
        return self


class ParsingResult(BaseModel):
    """
    OCR 엔진의 작업 결과를 래핑하는 클래스입니다.
    성공 여부와 데이터, 그리고 성능 측정을 위한 처리 시간을 포함합니다.
    """
    success: bool = Field(..., description="작업 성공 여부")
    data: Optional[WeightTicket] = Field(None, description="추출된 데이터 객체")
    error_message: Optional[str] = Field(None, description="실패 시 에러 메시지")
    processing_time_ms: float = Field(..., description="엔진 처리 시간 (밀리초)")