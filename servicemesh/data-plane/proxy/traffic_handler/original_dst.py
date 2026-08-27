# -*- coding: utf-8 -*-
"""원래 목적지 레지스트리 — 집행 경로가 쓰고 탐지 경로가 읽는다.

iptables REDIRECT는 egress의 목적지를 127.0.0.1:PROXY_PORT로 DNAT한다. 그래서 lo에서
프레임을 잡는 탐지 경로는 원래 목적지(예: K8s API 10.96.0.1:443)가 아니라 DNAT된 값을
본다. 그러면:

  1. 컨버터가 dst_port로 라우팅을 정하는데(NEVER_BENIGN_FLOW_PORTS = {443,6443,...}),
     프레임의 dst_port가 9011이라 그 분기를 못 탄다 → k1/k2(HTTPS 정찰) 탐지 실패.
  2. 판정을 기록하는 session_id가 DNAT 5-tuple 기반이 되어, 원래 목적지로 계산하는
     집행 경로의 session_id와 어긋난다.
  3. 관측된 dst_ip가 127.0.0.1이 되어 benign 엣지가 external로 뭉친다.

집행 경로는 SO_ORIGINAL_DST로 원래 목적지를 이미 안다. 연결을 받을 때 그 값을
(소스 IP, 소스 포트) 키로 등록해두면, 탐지 경로가 outbound 프레임에서 같은 키로 원래
목적지를 되찾아 위 셋을 모두 바로잡을 수 있다.
"""

import threading


class OriginalDstRegistry:
    """(src_ip, src_port) → (dst_ip, dst_port). TTL로 오래된 항목을 지운다."""

    def __init__(self, ttl, clock):
        self._ttl = ttl
        self._clock = clock
        self._lock = threading.Lock()
        self._map = {}

    def register(self, src_ip, src_port, dst_ip, dst_port):
        with self._lock:
            self._map[(src_ip, src_port)] = (dst_ip, dst_port, self._clock())
            self._evict_locked()

    def resolve(self, src_ip, src_port):
        with self._lock:
            entry = self._map.get((src_ip, src_port))
            if entry is None:
                return None
            dst_ip, dst_port, ts = entry
            if self._clock() - ts > self._ttl:
                del self._map[(src_ip, src_port)]
                return None
            return dst_ip, dst_port

    def _evict_locked(self):
        # 등록은 연결마다 일어나므로 여기서 만료분을 청소해 무한 증가를 막는다.
        if len(self._map) < 4096:
            return
        now = self._clock()
        stale = [k for k, (_, _, ts) in self._map.items() if now - ts > self._ttl]
        for k in stale:
            del self._map[k]
