# -*- coding: utf-8 -*-
"""탐지 경로 — 프레임을 종단 어댑터에 넘기고 돌아온 판정을 기록한다.

Algorithm 1의 line 1~8에 해당한다.

    ParseMeta → GetSessionID → GetSessionBuf → Preprocess → Append
    → (윈도우 w가 차면) BuildImage → Classify

ParseMeta·GetSessionID가 Traffic Handler의 몫이고, 그 뒤는 전부 종단 어댑터
(adapter.py) 너머의 일이다. 판정 결과는 VerdictStore에 남고 집행 경로(proxy.py)가
세션 id로 조회한다.

캡처 지점을 loopback으로 잡은 이유:
    논문 Algorithm 1의 입력은 T_main, 즉 '메인 컨테이너에서 나온 트래픽'이다.
    iptables가 ingress·egress를 모두 프록시로 리다이렉트하므로 메인 컨테이너의
    모든 트래픽은 프록시와의 loopback 구간을 지난다. 여기서 잡으면 (1) 정확히
    T_main만 잡히고 (2) 프록시가 외부로 내보내기 '전에' 잡히므로 Relay·Drop을
    적용할 시간이 남는다. eth0에서 잡으면 이미 나간 뒤라 늦다.
"""

import logging
import threading

from .ports import SessionObservation
from .session import is_from_main_container, last_packet_direction, parse_session

logger = logging.getLogger("traffic-handler.detection")


class DetectionPipeline:
    def __init__(self, source, adapter, verdicts, target_port, proxy_port, telemetry=None):
        self._source = source
        self._adapter = adapter
        self._verdicts = verdicts
        self._target_port = target_port
        self._proxy_port = proxy_port
        self._telemetry = telemetry
        self._max_sessions = adapter.max_sessions
        self._stop = threading.Event()
        self._thread = None

    def process_frame(self, frame):
        """프레임 1개를 처리한다. 판정이 나왔으면 Detection을, 아니면 None."""
        key = parse_session(frame)
        if key is None:
            return None
        if not is_from_main_container(key, self._target_port, self._proxy_port):
            return None

        session_id = key.session_id(self._max_sessions)
        detection = self._adapter.analyze(session_id, frame)
        if detection is None:
            return None  # 윈도우 미충족 — Algorithm 1 line 6의 조건 미달

        # 마지막 패킷의 방향과 5-tuple을 판정과 함께 기록한다. 집행 경로가 연결 종류로
        # 추론하는 대신 여기서 관측한 값을 쓰고, 텔레메트리가 그대로 실어 보낸다.
        observation = SessionObservation(
            detection=detection,
            direction=last_packet_direction(key, self._target_port, self._proxy_port),
            src_ip=key.src_ip, src_port=key.src_port,
            dst_ip=key.dst_ip, dst_port=key.dst_port,
        )
        self._verdicts.put(session_id, observation)
        # benign 시퀀스는 개별 이벤트가 없으므로 집계 카운터만 올린다.
        # cleared/drop/relay는 집행 경로에서 emit되며 그때 집계된다.
        if self._telemetry is not None and not detection.is_malicious:
            self._telemetry.incr("benign")
        if detection.is_malicious:
            logger.warning(
                "이상 판정: session=%d score=%.4f dir=%s %s:%d→%s:%d",
                session_id, detection.score, observation.direction,
                key.src_ip, key.src_port, key.dst_ip, key.dst_port,
            )
        return observation

    def run(self):
        try:
            frames = self._source.frames()
        except (OSError, AttributeError) as exc:
            # NET_RAW capability가 없거나 AF_PACKET이 없는 환경(개발 PC 등).
            # 탐지 없이 Forward 전용으로 동작한다.
            logger.error("패킷 캡처를 시작할 수 없음 — Forward 전용으로 동작: %s", exc)
            return

        while True:
            try:
                frame = next(frames)
            except StopIteration:
                break
            except (OSError, AttributeError) as exc:
                logger.error("패킷 캡처 중단 — Forward 전용으로 동작: %s", exc)
                break
            if self._stop.is_set():
                break
            try:
                self.process_frame(frame)
            except Exception:
                logger.exception("프레임 처리 실패 — 다음 프레임으로 진행")

    def start(self):
        self._thread = threading.Thread(target=self.run, name="detection", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        self._source.close()
