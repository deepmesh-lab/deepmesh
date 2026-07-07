# 필요 패키지: torch, scikit-learn, joblib, requests, numpy
# pip install torch scikit-learn joblib requests numpy

"""
proxy_detection.py — Algorithm 1 구현

논문: Lightweight Service Mesh for Intrusion Detection using KD-CNN
Algorithm 1: Proxy 요청 처리
  1. traffic = convert(request)         # 패킷 → 5×1479 이미지
  2. embedding = student.forward(traffic)
  3. score = ocsvm.score(embedding)
  4. if score >= threshold:
       return Forward(request, target_service)  # 정상 → 목적지로 전달
  5. else:
       result = control_plane.verify(request)
       if result == ALLOW:
           return Relay(request, target_service)  # CP 허가 → 전달
       else:
           return Drop(request)                    # CP 거부 → 차단
"""

import base64
import logging
import os
from collections import deque
from typing import Optional

import joblib
import numpy as np
import requests
import torch

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# AnomalyDetector
# ---------------------------------------------------------------------------

class AnomalyDetector:
    """
    Student TorchScript + OCSVM 기반 이상 탐지기.

    모델 파일:
      - {model_dir}/student_ts.pt  : torch.jit.load으로 로드
      - {model_dir}/ocsvm.pkl      : joblib.load으로 로드
    """

    def __init__(self, model_dir: str, device: str = "cpu"):
        self.device = torch.device(device)
        self.threshold: float = 0.0  # OCSVM decision_function 기준값

        # Student TorchScript 모델 로드
        student_path = os.path.join(model_dir, "student_ts.pt")
        if not os.path.exists(student_path):
            raise FileNotFoundError(f"Student 모델을 찾을 수 없음: {student_path}")
        self.student: torch.jit.ScriptModule = torch.jit.load(
            student_path, map_location=self.device
        )
        self.student.eval()
        logger.info("Student TorchScript 모델 로드 완료: %s", student_path)

        # OCSVM 모델 로드
        ocsvm_path = os.path.join(model_dir, "ocsvm.pkl")
        if not os.path.exists(ocsvm_path):
            raise FileNotFoundError(f"OCSVM 모델을 찾을 수 없음: {ocsvm_path}")
        self.ocsvm = joblib.load(ocsvm_path)
        logger.info("OCSVM 모델 로드 완료: %s", ocsvm_path)

    def convert_request(self, raw_bytes: bytes) -> torch.Tensor:
        """
        HTTP 요청 바이트 → 5×1479 이미지 텐서 (Algorithm 1 Step 1).

        변환 규칙:
          - raw_bytes를 1479바이트 단위로 청크 분할
          - 1479바이트보다 짧은 청크는 0으로 패딩
          - 청크가 5개 미만이면 기존 청크를 반복해 5행 채움
          - 5개 초과이면 앞 5개만 사용
          - 최종 shape: (1, 5, 1479) float32, 값 범위 [0, 1] (÷255)

        Args:
            raw_bytes: HTTP 요청 원시 바이트

        Returns:
            torch.Tensor shape (1, 5, 1479), dtype float32
        """
        PKT_LEN = 1479
        WINDOW = 5

        # raw_bytes를 PKT_LEN 단위로 청크 분할
        chunks: list[np.ndarray] = []
        for i in range(0, max(len(raw_bytes), 1), PKT_LEN):
            chunk = raw_bytes[i : i + PKT_LEN]
            arr = np.frombuffer(chunk, dtype=np.uint8).copy()
            if len(arr) < PKT_LEN:
                arr = np.pad(arr, (0, PKT_LEN - len(arr)), constant_values=0)
            chunks.append(arr)

        # 5개 초과 → 앞 5개만 사용
        if len(chunks) > WINDOW:
            chunks = chunks[:WINDOW]

        # 5개 미만 → 반복해서 채움
        while len(chunks) < WINDOW:
            chunks.append(chunks[len(chunks) % len(chunks)])

        # (5, 1479) numpy 배열 → (1, 5, 1479) float32 텐서
        matrix = np.stack(chunks, axis=0).astype(np.float32) / 255.0  # (5, 1479)
        tensor = torch.from_numpy(matrix).unsqueeze(0)                 # (1, 5, 1479)
        return tensor.to(self.device)

    def detect(self, raw_bytes: bytes) -> tuple[str, float]:
        """
        Algorithm 1 Step 1~3: 패킷 변환 → embedding → OCSVM 점수 산출.

        Args:
            raw_bytes: HTTP 요청 원시 바이트

        Returns:
            (label, score)
              label: "normal" | "anomaly"
              score: OCSVM decision_function 값 (양수=정상, 음수=이상)
        """
        # Step 1: 패킷 → 텐서
        tensor = self.convert_request(raw_bytes)  # (1, 5, 1479)

        # Step 2: Student forward → embedding
        with torch.no_grad():
            embedding = self.student(tensor)       # (1, embed_dim)
        embedding_np = embedding.cpu().numpy()

        # Step 3: OCSVM decision_function → score
        score: float = float(self.ocsvm.decision_function(embedding_np)[0])

        label = "normal" if score >= self.threshold else "anomaly"
        logger.debug("탐지 결과: label=%s, score=%.4f", label, score)
        return label, score


# ---------------------------------------------------------------------------
# ProxyHandler
# ---------------------------------------------------------------------------

class ProxyHandler:
    """
    Algorithm 1 전체 구현 — Forward / Drop / Relay 결정.

    Args:
        target_host:        실제 서비스 host:port (예: "backend:8080")
        control_plane_url:  Control Plane URL (예: "http://cp-service:9090")
        model_dir:          student_ts.pt, ocsvm.pkl이 위치한 디렉토리
        device:             torch device 문자열 (기본 "cpu")
    """

    def __init__(
        self,
        target_host: str,
        control_plane_url: str,
        model_dir: str,
        device: str = "cpu",
    ):
        self.target_host = target_host
        self.control_plane_url = control_plane_url.rstrip("/")
        self.detector = AnomalyDetector(model_dir, device)

    def handle(self, request_bytes: bytes, request_headers: dict) -> dict:
        """
        Algorithm 1 전체 실행.

        Args:
            request_bytes:   HTTP 요청 원시 바이트
            request_headers: HTTP 요청 헤더 dict

        Returns:
            {
                "action": "forward" | "relay" | "drop",
                "reason": str,
            }
        """
        # Step 1~3: 이상 탐지
        label, score = self.detector.detect(request_bytes)

        # Step 4: 정상 → Forward
        if label == "normal":
            logger.info("Forward: score=%.4f", score)
            return {"action": "forward", "reason": f"normal (score={score:.4f})"}

        # Step 5: 이상 감지 → Control Plane 검증
        logger.warning("이상 감지: score=%.4f, Control Plane 검증 요청", score)
        result = self._verify_with_control_plane(request_bytes, request_headers)

        if result.get("allow"):
            logger.info("Relay: CP 허가, score=%.4f, peer_ips=%s", score, result.get("peer_ips", []))
            return {
                "action": "relay",
                "peer_ips": result.get("peer_ips", []),
                "reason": f"anomaly but CP allowed (score={score:.4f})",
            }
        else:
            logger.warning("Drop: CP 거부, score=%.4f", score)
            return {
                "action": "drop",
                "peer_ips": [],
                "reason": f"anomaly, CP denied (score={score:.4f})",
            }

    def _verify_with_control_plane(
        self, request_bytes: bytes, headers: dict
    ) -> dict:
        """
        Control Plane에 이상 트래픽 검증 요청.

        엔드포인트: POST {control_plane_url}/send/internal_request_body
        Body:
            {
                "request_body": <base64 인코딩된 요청 바이트>,
                "headers":      <HTTP 헤더 dict>
            }
        타임아웃: 2초 (초과 시 drop 처리)

        Returns:
            {"allow": bool}  — 타임아웃/오류 시 {"allow": False}
        """
        url = f"{self.control_plane_url}/send/internal_request_body"
        payload = {
            "request_body": base64.b64encode(request_bytes).decode("utf-8"),
            "headers": headers,
            "source_ip": os.environ.get("POD_IP", ""),
        }
        try:
            resp = requests.post(url, json=payload, timeout=2.0)
            resp.raise_for_status()
            data = resp.json()
            return {
                "allow": bool(data.get("allow", False)),
                "peer_ips": list(data.get("peer_ips", [])),
            }
        except requests.exceptions.Timeout:
            logger.error("Control Plane 타임아웃 (2s) → Drop 처리")
            return {"allow": False, "peer_ips": []}
        except requests.exceptions.RequestException as exc:
            logger.error("Control Plane 요청 오류: %s → Drop 처리", exc)
            return {"allow": False, "peer_ips": []}


# ---------------------------------------------------------------------------
# PacketBuffer
# ---------------------------------------------------------------------------

class PacketBuffer:
    """
    실시간으로 들어오는 패킷을 window_size(기본 5)만큼 버퍼링.

    패킷이 window_size개 모이면 (window_size, pkt_len) 배열을 반환한다.
    버퍼가 가득 차지 않은 상태에서 flush()를 호출하면
    남은 패킷을 0으로 패딩해 반환한다.

    Args:
        window_size: 슬라이딩 윈도우 크기 (기본 5)
        pkt_len:     패킷 1개의 바이트 길이 (기본 1479)
    """

    def __init__(self, window_size: int = 5, pkt_len: int = 1479):
        self.window_size = window_size
        self.pkt_len = pkt_len
        self._buffer: deque[np.ndarray] = deque(maxlen=window_size)

    def _to_fixed(self, pkt_bytes: bytes) -> np.ndarray:
        """패킷 바이트를 pkt_len 크기의 uint8 배열로 변환 (자르기/패딩)."""
        arr = np.frombuffer(pkt_bytes[: self.pkt_len], dtype=np.uint8).copy()
        if len(arr) < self.pkt_len:
            arr = np.pad(arr, (0, self.pkt_len - len(arr)), constant_values=0)
        return arr

    def add(self, pkt_bytes: bytes) -> Optional[np.ndarray]:
        """
        패킷을 버퍼에 추가.

        Returns:
            버퍼가 window_size만큼 가득 찼을 때 (window_size, pkt_len) ndarray,
            아직 모자라면 None.
        """
        self._buffer.append(self._to_fixed(pkt_bytes))
        if len(self._buffer) == self.window_size:
            window = np.stack(list(self._buffer), axis=0)  # (window_size, pkt_len)
            logger.debug("PacketBuffer 윈도우 완성: shape=%s", window.shape)
            return window
        return None

    def flush(self) -> Optional[np.ndarray]:
        """
        버퍼에 남은 패킷을 0으로 패딩해 (window_size, pkt_len) 배열로 반환.

        버퍼가 비어 있으면 None을 반환한다.
        flush 후 버퍼는 초기화된다.
        """
        if not self._buffer:
            return None

        rows = list(self._buffer)
        # 부족한 행을 0 배열로 채움
        while len(rows) < self.window_size:
            rows.append(np.zeros(self.pkt_len, dtype=np.uint8))

        window = np.stack(rows, axis=0)  # (window_size, pkt_len)
        self._buffer.clear()
        logger.debug("PacketBuffer flush: shape=%s", window.shape)
        return window
