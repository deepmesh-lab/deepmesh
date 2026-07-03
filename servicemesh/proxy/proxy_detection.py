"""
proxy_detection.py — Data Plane 이상 탐지기 (경로 A: AF_PACKET raw 스니퍼 기반)

논문 "Lightweight Service Mesh for Intrusion Detection using KD-CNN" 의 Traffic Converter
+ Anomaly Detector 를 이식한다. 운영본 L7 HTTP 방식(요청 바디 1479 청크분할)은 폐기하고,
원본과 동일하게 **패킷 단위(19B 헤더 + payload) 세션별 5패킷 슬라이딩 윈도우 이미지** 를 만든다.

핵심 설계(develop.md §0 경로 A):
  - 일반 TCP 소켓 스트림에는 L2/L3/L4 헤더가 없다(커널이 제거). 따라서 19B 헤더를 얻으려면
    AF_PACKET raw 소켓으로 **완전한 Ethernet 프레임** 을 캡처해 C 파서에 넣어야 한다.
  - 스니퍼가 세션(5-tuple XOR)별로 이미지를 완성하면 KD-CNN+OCSVM 으로 이상 점수를 내고,
    verdict_map[session_id] 에 최신 판정을 기록한다.
  - 실제 차단(drop)/중계(relay)는 main.py 의 투명 프록시가 이 verdict_map 을 조회해 수행한다.
    프록시와 스니퍼는 **동일한 session_id(5-tuple XOR)** 로 자연스럽게 상관(correlation)된다.
"""

import ctypes
import logging
import os
import socket
import struct
import threading
import time
from dataclasses import dataclass
from typing import Optional

import joblib
import numpy as np
import torch

logger = logging.getLogger(__name__)

# ETH_P_ALL / AF_PACKET (Linux 전용). dev(Windows)에서는 import 시점엔 문제없고 sniffer 시작 시에만 필요.
ETH_P_ALL = 0x0003
IPPROTO_TCP = 6


def compute_session_id(src_ip: int, dst_ip: int, src_port: int, dst_port: int,
                       proto: int, max_sessions: int) -> int:
    """원본과 동일한 5-tuple XOR 해시. XOR 이므로 방향(정/역)에 무관해 프록시와 값이 일치한다."""
    return (src_ip ^ dst_ip ^ src_port ^ dst_port ^ proto) % max_sessions


@dataclass
class Verdict:
    is_malicious: bool
    score: float
    ts: float


# ---------------------------------------------------------------------------
# AnomalyDetector — C 파서 + KD-CNN(student) + OCSVM
# ---------------------------------------------------------------------------

class AnomalyDetector:
    """
    모델 파일 (MODEL_DIR):
      - student_ts.pt : torch.jit(TorchScript) student encoder
      - ocsvm.pkl     : OneClassSVM

    파서 라이브러리:
      - packet_parser_stack.so : VEC_LEN/WIN_SIZE 는 .so 의 getter 로 조회해 자동 정합.
        (학습 시 사용한 payload 길이와 동일한 .so 를 배포해야 학습-추론이 일치)
    """

    def __init__(self, model_dir: str, parser_so: str, device: str = "cpu"):
        self.device = torch.device(device)
        self.threshold: float = float(os.environ.get("SCORE_THRESHOLD", "0.0"))

        # --- C 파서 로드 ---
        if not os.path.exists(parser_so):
            raise FileNotFoundError(f"패킷 파서 .so 를 찾을 수 없음: {parser_so}")
        self.c = ctypes.CDLL(parser_so)
        for fn in ("get_vec_len", "get_win_size", "get_max_sessions",
                   "init_session_storage", "reset_session"):
            getattr(self.c, fn).restype = ctypes.c_int
        self.VEC_LEN = self.c.get_vec_len()
        self.WIN_SIZE = self.c.get_win_size()
        self.MAX_SESSIONS = self.c.get_max_sessions()
        self.c.parse_and_stack.argtypes = [
            ctypes.POINTER(ctypes.c_uint8), ctypes.c_size_t,
            ctypes.POINTER(ctypes.c_float), ctypes.c_uint32,
        ]
        self.c.parse_and_stack.restype = ctypes.c_int
        assert self.c.init_session_storage() == 0, "세션 스토리지 초기화 실패"
        logger.info("C 파서 로드: %s (VEC_LEN=%d, WIN_SIZE=%d)",
                    parser_so, self.VEC_LEN, self.WIN_SIZE)

        # --- 모델 로드 ---
        student_path = os.path.join(model_dir, "student_ts.pt")
        ocsvm_path = os.path.join(model_dir, "ocsvm.pkl")
        if not os.path.exists(student_path):
            raise FileNotFoundError(f"Student 모델 없음: {student_path}")
        if not os.path.exists(ocsvm_path):
            raise FileNotFoundError(f"OCSVM 모델 없음: {ocsvm_path}")
        self.student = torch.jit.load(student_path, map_location=self.device).eval().to(torch.float32)
        self.ocsvm = joblib.load(ocsvm_path)
        logger.info("모델 로드 완료: %s, %s", student_path, ocsvm_path)

    def _to_image(self, out_stack) -> torch.Tensor:
        """(VEC_LEN*WIN_SIZE,) flat float 배열 → (1,1,VEC_LEN,WIN_SIZE) 정규화 텐서."""
        stacked = np.ctypeslib.as_array(out_stack, shape=(self.VEC_LEN * self.WIN_SIZE,))
        t = torch.from_numpy(stacked).to(dtype=torch.float32).div(255.0)
        return t.reshape(1, 1, self.VEC_LEN, self.WIN_SIZE).contiguous()

    def process_frame(self, frame: bytes) -> Optional[tuple[int, bool, float]]:
        """
        완전한 Ethernet 프레임 1개 처리.
        Returns:
          (session_id, is_malicious, score)  — 세션 윈도우가 5개 차서 판정이 나왔을 때
          None                                — TCP 아님/파싱 실패/윈도우 미충족
        """
        if len(frame) < 54:
            return None
        # IP/TCP 인지 최소 확인: EtherType 0x0800(IPv4), proto=TCP
        if frame[12] != 0x08 or frame[13] != 0x00 or frame[23] != IPPROTO_TCP:
            return None

        src_ip = int.from_bytes(frame[26:30], "big")
        dst_ip = int.from_bytes(frame[30:34], "big")
        src_port = struct.unpack("!H", frame[34:36])[0]
        dst_port = struct.unpack("!H", frame[36:38])[0]
        session_id = compute_session_id(src_ip, dst_ip, src_port, dst_port,
                                        IPPROTO_TCP, self.MAX_SESSIONS)

        out_stack = (ctypes.c_float * (self.WIN_SIZE * self.VEC_LEN))()
        raw_buf = (ctypes.c_uint8 * len(frame)).from_buffer_copy(frame)
        ret = self.c.parse_and_stack(raw_buf, len(frame), out_stack, session_id)
        if ret != 1:
            return None  # 아직 윈도우 미충족 또는 파싱 실패

        img = self._to_image(out_stack)  # (1,1,VEC_LEN,WIN_SIZE)
        with torch.no_grad():
            feat = self.student(img).cpu().numpy()
            score = float(self.ocsvm.decision_function(feat)[0])
        is_malicious = score < self.threshold  # OCSVM: 음수 = 이상
        return session_id, is_malicious, score


# ---------------------------------------------------------------------------
# SessionSniffer — AF_PACKET raw 소켓으로 프레임 캡처 → 탐지 → verdict_map 갱신
# ---------------------------------------------------------------------------

class SessionSniffer:
    """
    별도 스레드에서 pod 네트워크 네임스페이스의 프레임을 캡처한다.
    verdict_map(session_id → Verdict)은 프록시(main.py)와 공유되는 thread-safe dict.
    """

    def __init__(self, detector: AnomalyDetector, iface: Optional[str] = None,
                 verdict_ttl: float = 10.0):
        self.detector = detector
        self.iface = iface  # None 이면 모든 인터페이스
        self.verdict_ttl = verdict_ttl
        self.verdict_map: dict[int, Verdict] = {}
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._sock: Optional[socket.socket] = None

    def get_verdict(self, session_id: int) -> Optional[Verdict]:
        with self._lock:
            v = self.verdict_map.get(session_id)
        if v is None:
            return None
        if time.time() - v.ts > self.verdict_ttl:
            return None  # 오래된 판정은 무효(세션 재사용/충돌 방지)
        return v

    def _set_verdict(self, session_id: int, is_malicious: bool, score: float):
        with self._lock:
            self.verdict_map[session_id] = Verdict(is_malicious, score, time.time())

    def start(self):
        threading.Thread(target=self._run, name="session-sniffer", daemon=True).start()

    def stop(self):
        self._stop.set()
        if self._sock:
            try:
                self._sock.close()
            except Exception:
                pass

    def _run(self):
        try:
            self._sock = socket.socket(socket.AF_PACKET, socket.SOCK_RAW,
                                       socket.htons(ETH_P_ALL))
            if self.iface:
                self._sock.bind((self.iface, 0))
            self._sock.settimeout(1.0)
        except (AttributeError, OSError) as exc:
            # AF_PACKET 은 Linux 전용 + CAP_NET_RAW 필요
            logger.error("raw 소켓 생성 실패(%s). NET_RAW 권한/Linux 여부 확인.", exc)
            return

        logger.info("SessionSniffer 시작 (iface=%s)", self.iface or "any")
        while not self._stop.is_set():
            try:
                frame = self._sock.recv(65535)
            except socket.timeout:
                continue
            except OSError:
                break
            result = self.detector.process_frame(frame)
            if result is None:
                continue
            session_id, is_malicious, score = result
            self._set_verdict(session_id, is_malicious, score)
            if is_malicious:
                logger.warning("이상 세션 감지: sid=%d score=%.4f", session_id, score)
