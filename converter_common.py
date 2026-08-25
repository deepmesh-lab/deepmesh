"""
converter_common.py — 서비스별 컨버터가 공유하는 공통 기반.

서비스별 파일(<svc>_converter.py)로 분리하면서, 아래 두 가지는 이 파일에 단일 소스로 남긴다.

  1) 특징 추출 함수(verbatim 블록)
     http_features / sql_features / flow_features / mysql_resp_features / fe_features /
     frame_info / _temporal / 정규식·상수. preprocess_semantic.py 에서 그대로 이식한 것으로,
     모델이 이 특징들로 학습됐다. 5개 파일에 복사해두면 언젠가 한쪽만 고쳐져 조용히 어긋난다.
     수정 금지. 서비스별로 갈라져야 하는 건 '어떤 특징을 쓸지'(=라우팅)이지 '특징이 무엇인지'가 아니다.

  2) BaseConverter — 세션 상태(f18/f19), to_image, process, bind_detector 등 서비스 무관 배선.
     서비스별 파일은 이 클래스를 상속해 extract() 하나만 정의한다.

이미지 방향: (H=20 특징, W=5 패킷). Detector 는 (1,1,20,5) 로 넣는다.
"""
from __future__ import annotations

import os
import re
import hmac
import hashlib
import struct
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import numpy as np

WIN_SIZE = 5
FEAT_LEN = 20
MAX_SESSIONS = 65536
BLOCKED_PORTS = {443, 22, 9000}                  # 핸들러 규칙 차단 대상(원문). 아래 FLOW_PORTS 로 흡수.
BODY_FP_KEY = b"deepmesh-frontend-fp-v1"         # 런타임 핸들러 IsContentEqual HMAC 키와 동일해야 함
APISERVER_PORTS = {443, 6443}

# 이중 라우팅에서 'flow 로 본다'고 판단할 목적지 포트 집합.
#   k1/k2(:443/:6443 k8s API), e1/c2(:53 DNS, :443 HTTPS), d1(:3306 mysql), SSH(:22), exfil(:9000).
#   backend/frontend 서비스에서 이 포트로 나가는 egress 는 payload 대신 flow 메타로 이미지화
FLOW_PORTS = {443, 6443, 22, 9000, 53, 3306}
NEVER_BENIGN_FLOW_PORTS = {443, 6443, 22, 9000}   # 정상이 절대 안 쓰는 포트 → backend/frontend 이중라우팅 시 이것만 flow 이미지화(:3306 DB/:53 DNS 등 정상 east-west 는 forward)

def frame_info(buf: bytes):
    """(sid, src_ip, dst_ip, dst_port, tcp_flags, tcp_payload, ip_total_len) 또는 None.
    C 파서/런타임과 동일 오프셋 규약. (preprocess_semantic.py verbatim)"""
    if len(buf) < 54 or buf[12] != 0x08 or buf[13] != 0x00 or buf[23] != 6:
        return None
    ip_total_len = int.from_bytes(buf[16:18], "big")
    src_ip = int.from_bytes(buf[26:30], "big"); dst_ip = int.from_bytes(buf[30:34], "big")
    src_port = int.from_bytes(buf[34:36], "big"); dst_port = int.from_bytes(buf[36:38], "big")
    sid = (src_ip ^ dst_ip ^ src_port ^ dst_port ^ 6) % MAX_SESSIONS
    ip_ihl = (buf[14] & 0x0F) * 4
    tcp_off = 14 + ip_ihl
    if len(buf) < tcp_off + 20:
        return sid, src_ip, dst_ip, dst_port, 0, b"", ip_total_len
    tcp_flags = buf[tcp_off + 13]
    data_off = ((buf[tcp_off + 12] >> 4) & 0xF) * 4
    payload = buf[tcp_off + data_off:] if len(buf) > tcp_off + data_off else b""
    return sid, src_ip, dst_ip, dst_port, tcp_flags, payload, ip_total_len


def _is_tls(payload: bytes) -> bool:
    if len(payload) < 3:
        return False
    return payload[0] in (0x14, 0x15, 0x16, 0x17) and payload[1] == 0x03 and payload[2] in (0x01, 0x02, 0x03, 0x04)


_REQ_LINE = re.compile(rb'^(GET|POST|PUT|DELETE|HEAD|PATCH|OPTIONS)\s+(\S+)\s+HTTP/\d', re.I)
_STATUS_LINE = re.compile(rb'^HTTP/\d\.\d\s+(\d{3})')
_AUTH_HDR = re.compile(rb'\r\n[Aa]uthorization:\s*', re.I)
_SCAN_PAT = re.compile(rb'(\.env|\.git|/actuator|/admin|\.\./|\.aws|wp-login|/config\.|swagger)', re.I)
_INJ_PAT = re.compile(rb"(union\s+select|<script|';|--|/\*|or\s+1=1|drop\s+table)", re.I)
_NUM_SEG = re.compile(rb'/(\d+)')
_CTYPE = re.compile(rb'\r\n[Cc]ontent-[Tt]ype:\s*([^\r\n;]+)', re.I)
_CLEN = re.compile(rb'\r\n[Cc]ontent-[Ll]ength:\s*(\d+)', re.I)


def http_features(payload: bytes) -> np.ndarray:
    f = np.zeros(FEAT_LEN, dtype=np.float32)
    m = _REQ_LINE.match(payload)
    if not m:
        f[5] = 1.0
        if _AUTH_HDR.search(payload): f[16] = 1.0
        if _INJ_PAT.search(payload):  f[17] = 1.0
        return f
    method = m.group(1).upper(); path = m.group(2)
    f[{b'GET': 0, b'POST': 1, b'PUT': 2, b'DELETE': 3}.get(method, 4)] = 1.0
    f[6] = 1.0 if path.startswith(b'/internal/') else 0.0
    f[7] = 1.0 if path.startswith(b'/api/') else 0.0
    q = path.find(b'?'); f[8] = 1.0 if q >= 0 else 0.0
    path_only = path[:q] if q >= 0 else path
    f[9] = min(path_only.count(b'/') / 10.0, 1.0)
    f[10] = min(len(path_only) / 100.0, 1.0)
    nums = _NUM_SEG.findall(path_only)
    if nums:
        f[11] = 1.0
        f[12] = min(np.log1p(int(nums[-1])) / 15.0, 1.0)
        segs = [s for s in path_only.split(b'/') if s]
        f[13] = len(nums) / max(len(segs), 1)
    f[14] = 1.0 if _SCAN_PAT.search(path) else 0.0
    f[15] = 1.0 if method in (b'POST', b'PUT', b'DELETE') else 0.0
    f[16] = 1.0 if _AUTH_HDR.search(payload) else 0.0
    f[17] = 1.0 if _INJ_PAT.search(payload) else 0.0
    return f


_SQL_KW = {b'SELECT': 0, b'SHOW': 1, b'INSERT': 2, b'UPDATE': 3, b'DELETE': 4}


def sql_features(payload: bytes) -> np.ndarray:
    f = np.zeros(FEAT_LEN, dtype=np.float32)
    up = payload.upper()
    found = False
    for kw, idx in _SQL_KW.items():
        if kw in up:
            f[idx] = 1.0; found = True
    if not found:
        f[9] = 1.0
        return f
    f[5] = 1.0 if (b'INFORMATION_SCHEMA' in up or b'SHOW DATABASES' in up) else 0.0
    f[6] = 1.0 if (b'AUTH_DB.' in up or b'COMMENTS_DB.' in up or b'POSTS_DB.' in up) else 0.0
    f[7] = 1.0 if (b'SELECT *' in up or b'SELECT ALL' in up) else 0.0
    f[8] = 1.0 if b'LIMIT' in up else 0.0
    f[10] = min(len(payload) / 200.0, 1.0)
    return f


def _temporal(dt, window_bytes):
    """공통 시간특징 → (f18, f19). 수명 독립(세션 누적 아님).
       f18=Δt(직전 이미지패킷과 간격, 초, 60s cap): beacon 주기/enumeration rate.
       f19=윈도우 볼륨(직전 WIN_SIZE 이미지패킷 바이트 합, log): exfil 볼륨. 둘 다 커넥션 수명과 무관."""
    f18 = min(float(np.log1p(min(max(dt, 0.0), 60.0))) / 4.0, 1.0)
    f19 = min(float(np.log1p(max(window_bytes, 0.0))) / 14.0, 1.0)
    return f18, f19


def flow_features(dst_port: int, tcp_flags: int, payload: bytes, iplen: int = 0) -> np.ndarray:
    f = np.zeros(FEAT_LEN, dtype=np.float32)
    n = (iplen - 40) if iplen >= 40 else len(payload)
    f[0] = 1.0 if dst_port in APISERVER_PORTS else 0.0
    f[1] = 1.0 if dst_port == 3306 else 0.0
    f[2] = 1.0 if dst_port == 8080 else 0.0
    f[3] = 1.0 if dst_port >= 32768 else 0.0
    f[4] = 1.0 if dst_port in (22, 9000) else 0.0
    f[5] = 1.0 if _is_tls(payload) else 0.0
    f[6] = 1.0 if (tcp_flags & 0x02) else 0.0
    f[7] = 1.0 if (tcp_flags & 0x05) else 0.0
    f[8] = 1.0 if n > 0 else 0.0
    if n < 100:  f[9] = 1.0
    elif n < 500:  f[10] = 1.0
    elif n < 1000: f[11] = 1.0
    else:          f[12] = 1.0
    f[13] = min(n / 1500.0, 1.0)
    # f[14-16] 예약(0). f[17]=DNS(:53) flow 전용(e1 DNS 터널). f[18]/f[19]=공통 시간특징은 extract 에서 부여.
    f[17] = 1.0 if dst_port == 53 else 0.0
    return f



def mysql_resp_features(payload: bytes) -> np.ndarray:
    f = np.zeros(FEAT_LEN, dtype=np.float32)
    if len(payload) < 5:
        f[9] = 1.0
        return f
    b = payload[4]
    if b == 0x00: f[0] = 1.0
    elif b == 0xFF: f[1] = 1.0
    elif b == 0xFE: f[2] = 1.0
    else: f[3] = 1.0
    n = len(payload)
    if n < 50: f[4] = 1.0
    elif n < 200: f[5] = 1.0
    elif n < 500: f[6] = 1.0
    elif n < 1000: f[7] = 1.0
    else: f[8] = 1.0
    f[10] = min(n / 1500.0, 1.0)
    if b > 0x00 and b != 0xFF and b != 0xFE:
        sample = payload[5:37]
        f[11] = len(set(sample)) / 32.0 if sample else 0.0
    printable = sum(1 for x in payload[5:105] if 32 <= x < 127)
    f[12] = printable / max(len(payload[5:105]), 1)
    if n >= 1400: f[13] = 1.0
    return f


def _body_fp(body: bytes) -> Tuple[float, float]:
    if not body:
        return 0.0, 0.0
    d = hmac.new(BODY_FP_KEY, body, hashlib.sha256).digest()
    return d[0] / 255.0, d[1] / 255.0


def fe_features(payload: bytes) -> np.ndarray:
    f = np.zeros(FEAT_LEN, dtype=np.float32)
    m = _REQ_LINE.match(payload)
    if m:
        f[0] = 1.0
        method = m.group(1).upper(); path = m.group(2)
        f[2] = 1.0 if method == b'GET' else 0.0
        f[3] = 1.0 if method in (b'POST', b'PUT', b'DELETE') else 0.0
        f[4] = 1.0 if _SCAN_PAT.search(path) else 0.0
        f[5] = 1.0 if (path.startswith(b'/api/') or path.startswith(b'/internal/')) else 0.0
        q = path.find(b'?'); path_only = path[:q] if q >= 0 else path
        f[6] = min(path_only.count(b'/') / 10.0, 1.0)
        f[7] = min(len(path_only) / 100.0, 1.0)
        f[8] = 1.0 if _NUM_SEG.search(path_only) else 0.0
        return f
    sm = _STATUS_LINE.match(payload)
    if sm:
        f[1] = 1.0
        code = int(sm.group(1)); f[9 + min(code // 100 - 2, 3)] = 1.0
        ct = _CTYPE.search(payload); cl = _CLEN.search(payload)
        if ct:
            c = ct.group(1).lower()
            if b'html' in c: f[13] = 1.0
            elif b'javascript' in c or b'css' in c: f[14] = 1.0
        hdr_end = payload.find(b'\r\n\r\n')
        body = payload[hdr_end + 4:] if hdr_end >= 0 else b""
        clen = int(cl.group(1)) if cl else len(body)
        f[15] = min(np.log1p(clen) / 15.0, 1.0)
        f[16], f[17] = _body_fp(body)
        return f
    return f

# 패킷 표현 + pcap 읽기 + (테스트용) 합성 프레임
@dataclass
class Packet:
    """egress 패킷 하나의 파싱된 필드."""
    session_id: int
    src_ip: int
    dst_ip: int
    dst_port: int
    tcp_flags: int
    payload: bytes
    iplen: int
    ts: float = 0.0                     # 패킷 도착 시각(초). read_pcap=pcap ts, 런타임=프록시 수신시각. Δt 계산용.


def _ip_to_int(ip: str) -> int:
    return int.from_bytes(bytes(int(o) for o in ip.split(".")), "big")


def build_frame(src_ip: str, dst_ip: str, src_port: int, dst_port: int,
                payload: bytes = b"", flags: int = 0x18) -> bytes:
    """frame_info 로 파싱 가능한 최소 Ethernet+IPv4+TCP 프레임을 만든다(테스트/합성 데이터용).
    flags 기본 0x18 = PSH|ACK. iplen 은 실제 헤더+payload 길이로 채워 flow 크기 특징이 정상 동작."""
    eth = b"\x00" * 12 + b"\x08\x00"                       # dst/src MAC placeholder + EtherType IPv4
    ip_src = bytes(int(o) for o in src_ip.split("."))
    ip_dst = bytes(int(o) for o in dst_ip.split("."))
    ip_total = 20 + 20 + len(payload)
    ip = bytes([0x45, 0x00]) + struct.pack(">H", ip_total) + b"\x00\x00\x40\x00\x40\x06\x00\x00" + ip_src + ip_dst
    tcp = struct.pack(">HH", src_port, dst_port) + b"\x00\x00\x00\x00" + b"\x00\x00\x00\x00" \
        + bytes([0x50, flags]) + b"\xff\xff\x00\x00\x00\x00"   # data-offset 0x50 = 20B, no options
    return eth + ip + tcp + payload


def make_packet(src_ip: str, dst_ip: str, src_port: int, dst_port: int,
                payload: bytes = b"", flags: int = 0x18, ts: float = 0.0) -> Packet:
    """build_frame -> frame_info 를 거쳐 Packet 을 만든다(런타임 파싱 경로와 동일하게 검증).
    ts: 합성 패킷의 도착 시각(초). 시간 특징을 테스트하려면 세션 내에서 증가시켜 전달."""
    fi = frame_info(build_frame(src_ip, dst_ip, src_port, dst_port, payload, flags))
    sid, sip, dip, dport, tflags, pl, iplen = fi
    return Packet(sid, sip, dip, dport, tflags, pl, iplen, ts)


def read_pcap(path: str, pod_ip: str = "auto", limit: Optional[int] = None) -> List[Packet]:
    """pcap 을 읽어 egress(src==pod) Packet 리스트로. preprocess 와 동일하게 inbound 는 제외.
    pod_ip='auto' 면 첫 프레임의 src_ip 를 pod 로 간주(단일 침해 pod pcap 가정).
    limit: 스캔할 최대 프레임 수(거대 pcap 에서 앞부분만 읽어 세션 표본 확보). None 이면 전체."""
    import dpkt
    auto = (pod_ip == "auto")
    gate = None if auto else _ip_to_int(pod_ip)
    out: List[Packet] = []
    with open(path, "rb") as f:
        for i, (_ts, buf) in enumerate(dpkt.pcap.Reader(f)):
            if limit is not None and i >= limit:
                break
            fi = frame_info(bytes(buf))
            if fi is None:
                continue
            sid, sip, dip, dport, tflags, payload, iplen = fi
            if auto and gate is None:
                gate = sip
            if gate is not None and sip != gate:
                continue
            out.append(Packet(sid, sip, dip, dport, tflags, payload, iplen, float(_ts)))
    return out


# 서비스 -> 네이티브 표현(preprocess SVC_KIND 와 동일)
SVC_KIND = {"auth": "flow", "post": "backend", "comment": "backend",
            "frontend": "frontend", "mysql": "flow"}


@dataclass
class ConvResult:
    session_id: int
    image: np.ndarray            # (18,5)
    is_benign: bool
    score: float
    threshold: float


class BaseConverter:
    """서비스 무관 공통 배선. 서비스별 파일이 상속해 extract() 만 구현한다.

    서브클래스가 정의해야 하는 것:
      SERVICE : str  — 서비스 이름("post" 등). Detector/모델 디렉터리 이름과 일치해야 한다.
      KIND    : str  — 네이티브 표현("flow"|"backend"|"frontend"). SVC_KIND 와 일치해야 한다.
      extract(pkt) -> Optional[Tuple[np.ndarray, bool]]
    """

    SERVICE: str = ""
    KIND: str = ""

    def __init__(self, out_dir: Optional[str] = None, stride: int = 1):
        if not self.SERVICE:
            raise TypeError("BaseConverter 를 직접 쓰지 말고 <svc>_converter 의 클래스를 쓰세요.")
        if SVC_KIND.get(self.SERVICE) != self.KIND:
            raise ValueError(f"{self.SERVICE}: KIND={self.KIND} 가 SVC_KIND 와 불일치")
        self.service = self.SERVICE
        self.kind = self.KIND
        self.stride = stride                       # 런타임=1 (핸들러가 이 값으로 emit 주기 결정)
        self.out_dir = out_dir
        self.detector = None                       # bind_detector 로 주입
        self._img_seq = 0
        self._sess_state = {}                       # 세션별 (last_ts, ring) — 공통 시간특징(f18/f19)
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)

    def bind_detector(self, detector) -> "BaseConverter":
        self.detector = detector
        return self

    def reset(self) -> None:
        """세션 상태 초기화. 새 pcap/세션 실행 전 호출(학습 _process_one_pcap 의 pcap 단위 리셋과 정합)."""
        self._sess_state.clear()

    def _update_sess(self, pkt: "Packet"):
        """이미지화되는 패킷에만 호출 → (dt, window_bytes). 수명독립(직전 WIN_SIZE 이미지패킷).
           ★ preprocess _process_one_pcap 와 동일 규칙·동일 순서."""
        stt = self._sess_state.setdefault(pkt.session_id, {"last": None, "ring": []})
        dt = 0.0 if stt["last"] is None else float(pkt.ts - stt["last"])
        stt["last"] = pkt.ts
        n = (pkt.iplen - 40) if pkt.iplen >= 40 else len(pkt.payload)
        stt["ring"].append(max(n, 0))
        if len(stt["ring"]) > WIN_SIZE:
            stt["ring"].pop(0)
        return dt, sum(stt["ring"])

    def _finish(self, pkt: "Packet", base: np.ndarray, isreq: bool):
        """이미지화 확정된 벡터에 공통 시간특징(f18=Δt, f19=윈도우볼륨)을 부여해 마무리.
           서비스별 extract() 의 마지막 두 줄을 대신한다(원본 (b) 단계와 동일)."""
        dt, wv = self._update_sess(pkt)
        base[18], base[19] = _temporal(dt, wv)
        return base, isreq

    # 1) 패킷 하나 -> (벡터, is_request) 또는 None(=탐지 제외, forward)
    def extract(self, pkt: "Packet") -> Optional[Tuple[np.ndarray, bool]]:
        raise NotImplementedError

    @staticmethod
    def _is_request(pkt: Packet, mode: str) -> bool:
        """방향 판정. HTTP 는 요청줄/상태줄로, flow 는 목적지 포트 휴리스틱으로.
           ephemeral(>=32768) 목적지 = 클라이언트로 돌아가는 '응답', 그 외 서비스/API/DB 포트 = '요청'."""
        if _REQ_LINE.match(pkt.payload):
            return True
        if _STATUS_LINE.match(pkt.payload):
            return False
        return pkt.dst_port < 32768              # flow: 서비스 포트 대상이면 요청으로 간주

    # 2) 완성된 5벡터 -> (20,5) 이미지 (학습 BuildImage 와 동일: stack axis=1)
    def to_image(self, vecs: List[np.ndarray]) -> np.ndarray:
        if len(vecs) != WIN_SIZE:
            raise ValueError(f"need {WIN_SIZE} vectors, got {len(vecs)}")
        img = np.stack(vecs, axis=1).astype(np.float32)      # (20,5)
        if self.out_dir:
            np.save(os.path.join(self.out_dir, f"img_{self._img_seq:05d}.npy"), img)
            self._img_seq += 1
        return img

    # 3) 이미지화 후 Detector 로 직접 전달(핸들러 경유 X)하고 판정을 되돌린다
    def process(self, session_id: int, vecs: List[np.ndarray]) -> ConvResult:
        if self.detector is None:
            raise RuntimeError("detector not bound (call bind_detector)")
        img = self.to_image(vecs)
        v = self.detector.detect(session_id, img)            # Converter -> Detector
        return ConvResult(session_id, img, v.is_benign, v.score, v.threshold)