# -*- coding: utf-8 -*-
"""세션별 최신 판정 보관소.

탐지 경로(스니퍼 스레드)가 쓰고 집행 경로(프록시 코루틴)가 읽으므로 thread-safe여야 한다.
"""

import threading
import time


class VerdictStore:
    """session_id → (Detection, 기록 시각). TTL이 지난 판정은 없는 것으로 본다."""

    def __init__(self, ttl, clock=time.monotonic):
        self._ttl = ttl
        self._clock = clock
        self._lock = threading.Lock()
        self._verdicts = {}

    def put(self, session_id, detection):
        with self._lock:
            self._verdicts[session_id] = (detection, self._clock())

    def get(self, session_id):
        with self._lock:
            entry = self._verdicts.get(session_id)
            if entry is None:
                return None
            detection, ts = entry
            if self._clock() - ts > self._ttl:
                del self._verdicts[session_id]
                return None
            return detection

    def get_any(self, session_ids):
        """후보 id 중 하나라도 이상 판정이면 그것을 돌려준다.

        하나의 프록시 연결은 클라이언트 쪽과 upstream 쪽에서 서로 다른 5-tuple을 가진다
        (프록시가 중간에서 소켓을 새로 열기 때문). 스니퍼가 둘 중 어느 쪽을 봤는지에
        따라 판정이 다른 id에 기록되므로 양쪽을 모두 조회한다.
        """
        found = None
        for session_id in session_ids:
            detection = self.get(session_id)
            if detection is None:
                continue
            if detection.is_malicious:
                return detection
            found = detection
        return found

    def purge_expired(self):
        now = self._clock()
        with self._lock:
            expired = [k for k, (_, ts) in self._verdicts.items() if now - ts > self._ttl]
            for k in expired:
                del self._verdicts[k]
        return len(expired)
