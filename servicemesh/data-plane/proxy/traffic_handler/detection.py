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
import struct
import threading

from .ports import SessionObservation
from .ports import SessionKey
from .session import is_from_main_container, last_packet_direction, parse_session

logger = logging.getLogger("traffic-handler.detection")


def _rewrite_dst(frame, dst_ip, dst_port):
    """프레임의 IP dst와 TCP dport를 바꾼 새 프레임을 만든다.

    체크섬은 고치지 않는다 — 컨버터의 frame_info는 오프셋만 읽고 체크섬을 검증하지
    않으므로 필요 없다. 오프셋 규약은 session.parse_session과 같다.
    """
    buf = bytearray(frame)
    ihl = (buf[14] & 0x0F) * 4
    tcp = 14 + ihl
    buf[14 + 16:14 + 20] = bytes(int(x) for x in dst_ip.split("."))
    buf[tcp + 2:tcp + 4] = struct.pack("!H", dst_port)
    return bytes(buf)


class DetectionPipeline:
    def __init__(self, source, adapter, verdicts, target_port, proxy_port,
                 telemetry=None, original_dst=None):
        self._source = source
        self._adapter = adapter
        self._verdicts = verdicts
        self._target_port = target_port
        self._proxy_port = proxy_port
        self._telemetry = telemetry
        # 집행 경로가 등록한 원래 목적지. iptables REDIRECT로 프레임의 목적지가 DNAT되어
        # 있어(dst=127.0.0.1:9011), 이걸로 원본을 되찾는다 (original_dst.py 참고).
        self._original_dst = original_dst
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

        # outbound(메인→프록시)면 DNAT된 목적지를 원래 목적지로 되돌린다. 컨버터의 포트
        # 라우팅과 세션 id, 관측 dst가 모두 원본을 기준으로 서야 집행 경로와 맞물린다.
        if self._original_dst is not None and key.dst_port == self._proxy_port:
            original = self._original_dst.resolve(key.src_ip, key.src_port)
            if original is not None:
                key = SessionKey(key.src_ip, original[0], key.src_port, original[1])
                frame = _rewrite_dst(frame, original[0], original[1])

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
            # 목적지를 함께 넘긴다. benign은 개별 이벤트로 남지 않으므로, 이걸 빼면
            # 대시보드가 평시 통신 경로(엣지)를 그릴 근거가 사라진다.
            self._telemetry.incr("benign", peer=observation.dst_ip)
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
