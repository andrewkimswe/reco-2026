"""
누리장터 크롤러 전용 데이터 저장소 (Persistence Layer)
- 이중 테이블 구조: 실제 공고 데이터(nuri_notices)와 수집 상태 로그(scrap_log)를 분리 관리합니다.
- 체크포인트 시스템: 수집 중단 시 중단 지점부터 다시 시작할 수 있도록 이력을 추적합니다.
- 데이터 정합성: SQLite 트랜잭션을 통해 공고 저장과 로그 기록의 원자성을 보장합니다.
"""

import sqlite3
import os
from datetime import datetime
from typing import List
from loguru import logger


class CrawlerStorage:
    def __init__(self, db_path="data/crawler_state.db"):
        """
        데이터베이스 연결 초기화 및 저장 디렉토리 생성
        - :memory: 경로 감지 시 테스트용 인메모리 DB로 동작합니다.
        """
        if db_path != ":memory:":
            db_dir = os.path.dirname(db_path)
            if db_dir:
                os.makedirs(db_dir, exist_ok=True)

        # 멀티스레드 환경 대응을 위해 check_same_thread=False 설정
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row  # 결과를 딕셔너리처럼 접근 가능하게 설정
        self._init_db()

    def _init_db(self):
        """테이블 및 인덱스 초기화: 데이터 스키마 정의"""
        with self.conn:
            # 1. 실제 수집된 공고의 상세 정보를 저장하는 메인 테이블
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS nuri_notices (
                    notice_id TEXT PRIMARY KEY,        -- 입찰공고번호 (PK)
                    title TEXT NOT NULL,               -- 공고명
                    org_name TEXT,                     -- 공고기관
                    notice_type TEXT,                  -- 공고유형
                    bid_method TEXT,                   -- 입찰방식
                    due_date TEXT,                     -- 마감일
                    announce_date TEXT,                -- 게시일
                    budget TEXT,                       -- 배정예산
                    demand_company TEXT,               -- 수요기관
                    detail_url TEXT,                   -- 상세페이지 URL
                    raw_data TEXT,                     -- API 응답 전문 (JSON 문자열)
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # 2. 공고별 수집 성공/실패 이력을 관리하는 체크포인트 테이블
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS scrap_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    notice_id TEXT NOT NULL UNIQUE,    -- 공고번호 (Unique Index)
                    status TEXT NOT NULL,              -- SUCCESS / FAILED
                    error_msg TEXT,                    -- 실패 시 에러 메시지
                    collected_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # 3. 크롤링 세션 관리 테이블: 전체 작업 단위의 통계 기록
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS crawl_sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    started_at DATETIME,               -- 작업 시작 시각
                    finished_at DATETIME,              -- 작업 종료 시각
                    total_found INTEGER DEFAULT 0,     -- 발견된 총 공고 수
                    total_collected INTEGER DEFAULT 0, -- 신규 수집 성공 수
                    total_skipped INTEGER DEFAULT 0,   -- 중복으로 건너뛴 수
                    total_errors INTEGER DEFAULT 0,    -- 처리 중 발생한 에러 수
                    status TEXT                        -- RUNNING / COMPLETED
                )
            """)

            # [성능 최적화] 검색 빈도가 높은 필드에 대한 인덱스 추가
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_scrap_log_status ON scrap_log(status)")
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_nuri_notices_org_name ON nuri_notices(org_name)")
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_nuri_notices_due_date ON nuri_notices(due_date)")

    def is_already_done(self, notice_id: str) -> bool:
        """증분 수집을 위해 특정 공고가 이미 성공적으로 저장되었는지 확인"""
        cur = self.conn.execute(
            "SELECT 1 FROM scrap_log WHERE notice_id = ? AND status = 'SUCCESS'",
            (notice_id,)
        )
        return cur.fetchone() is not None

    def save_notice(self, data: dict):
        """
        공고 데이터 저장 및 로그 기록을 하나의 트랜잭션으로 처리
        - 데이터는 저장되는데 로그가 안 남는 '데이터 불일치' 상황을 방지합니다.
        """
        try:
            with self.conn:
                # 1. 메인 데이터 저장 (이미 존재하면 덮어쓰기)
                self.conn.execute("""
                    INSERT OR REPLACE INTO nuri_notices 
                    (notice_id, title, org_name, notice_type, bid_method, 
                     due_date, announce_date, budget, demand_company, detail_url, raw_data)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    data.get('notice_id'), data.get('title'), data.get('org_name'),
                    data.get('notice_type'), data.get('bid_method'), data.get('due_date'),
                    data.get('announce_date'), data.get('budget'), data.get('demand_company'),
                    data.get('detail_url'), data.get('raw_data', '')
                ))

                # 2. 성공 로그 기록
                self.conn.execute("""
                    INSERT OR REPLACE INTO scrap_log (notice_id, status, collected_at)
                    VALUES (?, 'SUCCESS', ?)
                """, (data['notice_id'], datetime.now()))

        except Exception as e:
            logger.error(f"데이터 저장 실패 [{data.get('notice_id')}]: {e}")
            self.log_error(data.get('notice_id', 'UNKNOWN'), str(e))
            raise

    def log_error(self, notice_id: str, error_msg: str):
        """수집 실패 시 원인을 기록하여 추후 재시도 대상으로 관리"""
        with self.conn:
            self.conn.execute("""
                INSERT OR REPLACE INTO scrap_log (notice_id, status, error_msg, collected_at)
                VALUES (?, 'FAILED', ?, ?)
            """, (notice_id, error_msg, datetime.now()))

    def get_count(self) -> int:
        """저장된 유효 공고 데이터의 총 개수 반환"""
        cur = self.conn.execute("SELECT COUNT(*) FROM nuri_notices")
        return cur.fetchone()[0]

    def get_success_count(self) -> int:
        """성공적으로 수집 완료된 이력의 수 반환"""
        cur = self.conn.execute(
            "SELECT COUNT(*) FROM scrap_log WHERE status = 'SUCCESS'"
        )
        return cur.fetchone()[0]

    def get_failed_ids(self) -> List[str]:
        """실패한 공고 ID 목록을 반환하여 재시도 로직에서 활용 가능하게 함"""
        cur = self.conn.execute(
            "SELECT notice_id FROM scrap_log WHERE status = 'FAILED'"
        )
        return [row[0] for row in cur.fetchall()]

    def start_session(self) -> int:
        """새로운 크롤링 작업 세션 시작 기록"""
        with self.conn:
            cur = self.conn.execute("""
                INSERT INTO crawl_sessions (started_at, status)
                VALUES (?, 'RUNNING')
            """, (datetime.now(),))
            return cur.lastrowid

    def finish_session(self, session_id: int, stats: dict):
        """크롤링 세션 종료 및 최종 통계 업데이트"""
        with self.conn:
            self.conn.execute("""
                UPDATE crawl_sessions
                SET finished_at = ?,
                    total_found = ?,
                    total_collected = ?,
                    total_skipped = ?,
                    total_errors = ?,
                    status = 'COMPLETED'
                WHERE id = ?
            """, (
                datetime.now(),
                stats.get('found', 0),
                stats.get('collected', 0),
                stats.get('skipped', 0),
                stats.get('errors', 0),
                session_id
            ))

    def export_to_json(self, output_path: str):
        """저장된 모든 공고 데이터를 JSON 형식으로 내보내기"""
        import json
        cur = self.conn.execute("SELECT * FROM nuri_notices")
        data = [dict(row) for row in cur.fetchall()]

        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        logger.info(f"데이터 내보내기 완료: {output_path} ({len(data)}건)")

    def export_to_csv(self, output_path: str):
        """저장된 모든 공고 데이터를 엑셀 호환 CSV(UTF-8-BOM) 형식으로 내보내기"""
        import csv
        cur = self.conn.execute("SELECT * FROM nuri_notices")
        data = [dict(row) for row in cur.fetchall()]

        if not data:
            logger.warning("내보낼 데이터가 없습니다.")
            return

        with open(output_path, 'w', encoding='utf-8-sig', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=data[0].keys())
            writer.writeheader()
            writer.writerows(data)

        logger.info(f"데이터 내보내기 완료: {output_path} ({len(data)}건)")

    def get_stats(self) -> dict:
        """현재까지의 누적 수집 통계 요약"""
        total = self.get_count()
        success = self.get_success_count()
        cur = self.conn.execute(
            "SELECT COUNT(*) FROM scrap_log WHERE status = 'FAILED'"
        )
        failed = cur.fetchone()[0]

        return {
            'total_notices': total,
            'successful': success,
            'failed': failed
        }

    def close(self):
        """데이터베이스 연결 안전하게 종료"""
        self.conn.close()