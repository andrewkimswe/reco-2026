"""
누리장터 데이터 변환기 (Transformer)
- API의 가변적인 응답 구조를 표준화된 DTO(NoticeDTO)로 변환합니다.
- 데이터 정규화(날짜, 금액 등) 및 기본적인 비즈니스 검증을 수행합니다.
"""

from typing import List, Optional, Dict, Any
from dataclasses import dataclass, asdict
from loguru import logger

@dataclass
class NoticeDTO:
    """
    시스템 내부에서 공통으로 사용할 입찰공고 데이터 객체입니다.
    데이터베이스 저장 및 API 응답의 표준 규격을 정의합니다.
    """
    notice_id: str           # 입찰공고번호
    title: str               # 공고명
    org_name: str            # 공고기관
    notice_type: str         # 공고유형 (물품, 공사, 용역 등)
    bid_method: Optional[str] = None      # 입찰방식
    due_date: Optional[str] = None        # 마감일 (YYYY-MM-DD)
    announce_date: Optional[str] = None   # 게시일 (YYYY-MM-DD)
    budget: Optional[str] = None          # 배정예산
    demand_company: Optional[str] = None  # 수요기관
    detail_url: Optional[str] = None      # 상세페이지 URL
    raw_data: Optional[Dict[str, Any]] = None  # 원본 API 응답 데이터 (디버깅/이력용)

    def to_dict(self) -> dict:
        """DB insert 또는 JSON 직렬화를 위한 딕셔너리 변환"""
        return asdict(self)

    def is_valid(self) -> bool:
        """데이터 무결성을 위한 최소 조건 확인"""
        return bool(self.notice_id and self.title)


class NuriDataTransformer:
    """
    누리장터 API 응답 전문을 분석하여 정규화된 객체로 변환하는 클래스입니다.
    API 버전이나 응답 필드 변경에 유연하게 대응하도록 설계되었습니다.
    """

    # API 응답에서 공고 목록을 포함할 수 있는 주요 키 리스트
    LIST_KEYS = ['result', 'list', 'resultList', 'data', 'rows']

    def extract_notices(self, response: dict) -> List[dict]:
        """
        API 응답 딕셔너리에서 실제 공고 데이터가 담긴 리스트를 추출합니다.
        응답 포맷이 바뀌더라도 LIST_KEYS를 순회하며 데이터를 찾아냅니다.
        """
        if not isinstance(response, dict):
            logger.warning(f"예상치 못한 응답 포맷 (dict 아님): {type(response)}")
            return []

        # 정의된 키 중 존재하는 데이터를 반환
        for key in self.LIST_KEYS:
            if key in response and isinstance(response[key], list):
                logger.debug(f"데이터 추출 성공 (Key: {key}, Count: {len(response[key])})")
                return response[key]

        # 응답 자체가 리스트인 경우 대응
        if isinstance(response, list):
            return response

        logger.warning(f"응답에서 공고 목록 키를 찾을 수 없음: {list(response.keys())}")
        return []

    def transform_notice(self, raw_notice: dict) -> Optional[NoticeDTO]:
        """
        단일 원시(Raw) 데이터를 정규화된 NoticeDTO로 변환합니다.
        필드 매핑 및 날짜 형식 변환 로직을 포함합니다.
        """
        try:
            # 필수 식별자 추출
            notice_id = self._extract_notice_id(raw_notice)
            if not notice_id:
                return None

            # DTO 객체 매핑 및 데이터 정제
            dto = NoticeDTO(
                notice_id=notice_id,
                title=raw_notice.get('bidPbancNm') or raw_notice.get('pbancNm') or '제목없음',
                org_name=self._extract_org_name(raw_notice),
                notice_type=self._extract_notice_type(raw_notice),
                bid_method=raw_notice.get('bidMthdCdNm') or raw_notice.get('bidMthdNm'),
                due_date=self._normalize_date(raw_notice.get('onbsPrnmntEdDt') or raw_notice.get('bidClseDt')),
                announce_date=self._normalize_date(raw_notice.get('pbancPstgDt') or raw_notice.get('regDt')),
                budget=str(raw_notice.get('bscAmt') or raw_notice.get('presmptPrc') or ''),
                demand_company=raw_notice.get('dmndComp') or raw_notice.get('dmndCompNm'),
                detail_url=f"https://nuri.g2b.go.kr/nn/nnb/nnbb/selectBidNoceDetl.do?pbancNo={notice_id}",
                raw_data=raw_notice
            )

            return dto if dto.is_valid() else None

        except Exception as e:
            logger.error(f"데이터 변환 중 에러 발생 (NoticeID: {raw_notice.get('bidPbancNo')}): {e}")
            return None

    def enrich_with_detail(self, notice_dto: NoticeDTO, detail_data: dict) -> NoticeDTO:
        """
        상세 페이지 조회를 통해 얻은 추가 정보를 기존 DTO에 보강합니다.
        (예: 목록에는 없는 배정예산, 상세 공고 내용 등)
        """
        if not isinstance(detail_data, dict):
            return notice_dto

        # 상세 정보에서 누락된 필드 보강
        if not notice_dto.budget and 'bscAmt' in detail_data:
            notice_dto.budget = str(detail_data['bscAmt'])

        if not notice_dto.demand_company and 'dmndComp' in detail_data:
            notice_dto.demand_company = detail_data['dmndComp']

        # raw_data에 상세 정보를 합쳐서 보관
        if notice_dto.raw_data is not None:
            notice_dto.raw_data['detail'] = detail_data

        return notice_dto

    def _extract_notice_id(self, notice: dict) -> Optional[str]:
        """여러 가능한 필드명에서 공고 번호 추출"""
        return notice.get('bidPbancNo') or notice.get('bidNo') or notice.get('pbancNo')

    def _extract_org_name(self, notice: dict) -> str:
        """여러 가능한 필드명에서 기관명 추출"""
        return notice.get('grpNm') or notice.get('instNm') or notice.get('pbancInstNm') or '기관없음'

    def _extract_notice_type(self, notice: dict) -> str:
        """공고 유형 정규화"""
        return notice.get('prcmBsneSeCdNm') or notice.get('pbancTyCdNm') or '유형없음'

    def _normalize_date(self, date_str: Any) -> Optional[str]:
        """
        다양한 날짜 형식(YYYYMMDD, YYYY/MM/DD 등)을 YYYY-MM-DD 표준 형식으로 변환합니다.
        """
        if not date_str or not isinstance(date_str, str):
            return None

        clean_date = date_str.replace('/', '').replace('-', '').split(' ')[0]
        if len(clean_date) == 8: # YYYYMMDD
            return f"{clean_date[:4]}-{clean_date[4:6]}-{clean_date[6:8]}"
        return date_str


class ValidationError(Exception):
    """데이터 검증 실패 시 발생하는 사용자 정의 예외"""
    pass


def validate_notice_dto(dto: NoticeDTO) -> None:
    """
    비즈니스 규칙에 따른 데이터 최종 검증
    - 공고 번호 필수, 제목 유효성, 최소 길이 등을 체크합니다.
    """
    if not dto.notice_id:
        raise ValidationError("공고 번호 누락")

    if not dto.title or dto.title == '제목없음':
        raise ValidationError(f"유효하지 않은 공고명: {dto.title}")

    # 비정상적으로 짧은 공고 번호 차단
    if len(dto.notice_id) < 1:
        raise ValidationError(f"공고 번호 형식 오류: {dto.notice_id}")