# -*- coding: utf-8 -*-
"""Control Plane이 push한 형제 Pod 주소록.

Pod Info Provider가 주기마다 `POST /receive/pods_ip`로 자기 자신을 제외한 같은 서비스의
Pod 목록을 보낸다. 기동 직후 아직 못 받았으면 비어 있고, 그 동안 Relay는 건너뛴다.
"""

import threading


class PeerRegistry:
    def __init__(self):
        self._lock = threading.Lock()
        self._peers = []
        self._received = False

    def update(self, peers):
        """[{"name": ..., "ip": ...}, ...]로 통째 교체한다.

        Control Plane은 매 주기 전체 목록을 무조건 push하는 reconciliation 방식이므로
        증분 병합 없이 덮어쓰는 것이 맞다.
        """
        cleaned = [p for p in peers if isinstance(p, dict) and p.get("ip")]
        with self._lock:
            changed = [p["ip"] for p in cleaned] != [p["ip"] for p in self._peers]
            self._peers = cleaned
            self._received = True
        return changed

    def list(self):
        with self._lock:
            return list(self._peers)

    def has_peers(self):
        with self._lock:
            return bool(self._peers)

    @property
    def received(self):
        """주소록을 한 번이라도 받았는지. 미수신과 '형제 Pod 없음'을 구분한다."""
        with self._lock:
            return self._received
