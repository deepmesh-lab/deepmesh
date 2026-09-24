"""PCAP을 서비스별 특징 이미지(.npy)로 변환한다."""
import os, re, glob, hmac, hashlib
import numpy as np
import dpkt

HERE = os.path.dirname(os.path.abspath(__file__))
RESULT = os.environ.get("RESULT_DIR") or os.path.join(HERE, "..", "result")   # pcap 입력 경로
OUT = os.environ.get("DATA_DIR") or os.path.join(HERE, "data")                 # npy 출력 경로

WIN_SIZE = 5
MAX_SESSIONS = 65536
# stride=1은 매 패킷, 5는 겹치지 않는 윈도우
STRIDE = max(1, int(os.environ.get('STRIDE', '1')))
FEAT_LEN = 20
CAP_BENIGN, CAP_TEST, CAP_ATTACK = 180000, 36000, 20000
BLOCKED_PORTS = {443, 22, 9000}                  # 차단 대상 egress 포트
BODY_FP_KEY = b"deepmesh-frontend-fp-v1"         # 런타임 IsContentEqual과 동일한 키


def frame_info(buf: bytes):
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


def _ip_to_int(ip):
    return None if not ip else int.from_bytes(bytes(int(o) for o in ip.split(".")), "big")


def _is_tls(payload: bytes) -> bool:
    # TLS 레코드 헤더 확인
    if len(payload) < 3:
        return False
    return payload[0] in (0x14, 0x15, 0x16, 0x17) and payload[1] == 0x03 and payload[2] in (0x01, 0x02, 0x03, 0x04)


_REQ_LINE = re.compile(rb'^(GET|POST|PUT|DELETE|HEAD|PATCH|OPTIONS)\s+(\S+)\s+HTTP/\d', re.I)
_STATUS_LINE = re.compile(rb'^HTTP/\d\.\d\s+(\d{3})')
_AUTH_HDR = re.compile(rb'\r\n[Aa]uthorization:\s*', re.I)
_SCAN_PAT = re.compile(rb'(\.env|\.git|/actuator|/admin|\.\./|\.aws|wp-login|/config\.|swagger)', re.I)
_INJ_PAT  = re.compile(rb"(union\s+select|<script|';|--|/\*|or\s+1=1|drop\s+table)", re.I)
_NUM_SEG  = re.compile(rb'/(\d+)')
_CTYPE    = re.compile(rb'\r\n[Cc]ontent-[Tt]ype:\s*([^\r\n;]+)', re.I)
_CLEN     = re.compile(rb'\r\n[Cc]ontent-[Ll]ength:\s*(\d+)', re.I)


# 백엔드 HTTP 요청 특징
def http_features(payload: bytes) -> np.ndarray:
    f = np.zeros(FEAT_LEN, dtype=np.float32)
    m = _REQ_LINE.match(payload)
    if not m:
        f[5] = 1.0
        if _AUTH_HDR.search(payload): f[16] = 1.0
        if _INJ_PAT.search(payload):  f[17] = 1.0
        return f
    method = m.group(1).upper(); path = m.group(2)
    f[{b'GET':0, b'POST':1, b'PUT':2, b'DELETE':3}.get(method, 4)] = 1.0
    f[6] = 1.0 if path.startswith(b'/internal/') else 0.0
    f[7] = 1.0 if path.startswith(b'/api/') else 0.0
    q = path.find(b'?'); f[8] = 1.0 if q >= 0 else 0.0
    path_only = path[:q] if q >= 0 else path
    f[9]  = min(path_only.count(b'/') / 10.0, 1.0)
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


# SQL 요청 특징
_SQL_KW = {b'SELECT':0, b'SHOW':1, b'INSERT':2, b'UPDATE':3, b'DELETE':4}
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
    f[5]  = 1.0 if (b'INFORMATION_SCHEMA' in up or b'SHOW DATABASES' in up) else 0.0
    f[6]  = 1.0 if (b'AUTH_DB.' in up or b'COMMENTS_DB.' in up or b'POSTS_DB.' in up) else 0.0   # cross-DB 접근
    f[7]  = 1.0 if (b'SELECT *' in up or b'SELECT ALL' in up) else 0.0
    f[8]  = 1.0 if b'LIMIT' in up else 0.0
    f[10] = min(len(payload) / 200.0, 1.0)
    return f


# flow 특징
APISERVER_PORTS = {443, 6443}
def _dt_bucket(dt: float) -> float:
    # 학습과 런타임의 시간 차이를 줄이도록 패킷 간격을 구간화
    dt = max(float(dt), 0.0)
    if dt < 0.01:
        return 0.0
    elif dt < 0.1:
        return 0.25
    elif dt < 1.0:
        return 0.5
    elif dt < 10.0:
        return 0.75
    return 1.0


def _temporal(dt, window_bytes):
    # 패킷 간격과 윈도우 바이트 수
    f18 = _dt_bucket(dt)
    f19 = min(float(np.log1p(max(window_bytes, 0.0))) / 14.0, 1.0)
    return f18, f19


def flow_features(dst_port: int, tcp_flags: int, payload: bytes, iplen: int = 0) -> np.ndarray:
    f = np.zeros(FEAT_LEN, dtype=np.float32)
    n = (iplen - 40) if iplen >= 40 else len(payload)   # IP·TCP 헤더 40바이트 제외
    f[0] = 1.0 if dst_port in APISERVER_PORTS else 0.0        # Kubernetes API
    f[1] = 1.0 if dst_port == 3306 else 0.0                   # MySQL
    f[2] = 1.0 if dst_port == 8080 else 0.0                   # HTTP peer
    f[3] = 1.0 if dst_port >= 32768 else 0.0                  # ephemeral
    f[4] = 1.0 if dst_port in (22, 9000) else 0.0             # e1/c2 포트
    f[5] = 1.0 if _is_tls(payload) else 0.0                   # TLS 여부
    f[6] = 1.0 if (tcp_flags & 0x02) else 0.0                 # SYN
    f[7] = 1.0 if (tcp_flags & 0x05) else 0.0                 # FIN|RST
    f[8] = 1.0 if n > 0 else 0.0                              # payload 여부
    if   n < 100:  f[9] = 1.0
    elif n < 500:  f[10] = 1.0
    elif n < 1000: f[11] = 1.0
    else:          f[12] = 1.0
    f[13] = min(n / 1500.0, 1.0)
    f[17] = 1.0 if dst_port == 53 else 0.0                    # DNS
    return f


# MySQL 응답 유형·크기·텍스트 특징
def mysql_resp_features(payload: bytes) -> np.ndarray:
    f = np.zeros(FEAT_LEN, dtype=np.float32)
    if len(payload) < 5:
        f[9] = 1.0
        return f
    b = payload[4]                      # MySQL 패킷 유형
    if b == 0x00: f[0] = 1.0            # OK
    elif b == 0xFF: f[1] = 1.0          # ERR
    elif b == 0xFE: f[2] = 1.0          # EOF
    else: f[3] = 1.0                    # 결과셋 헤더·행
    n = len(payload)
    if n < 50: f[4] = 1.0
    elif n < 200: f[5] = 1.0
    elif n < 500: f[6] = 1.0
    elif n < 1000: f[7] = 1.0
    else: f[8] = 1.0
    f[10] = min(n / 1500.0, 1.0)
    if b > 0x00 and b != 0xFF and b != 0xFE:   # 첫 32바이트의 고유값 비율
        sample = payload[5:37]
        f[11] = len(set(sample)) / 32.0 if sample else 0.0
    printable = sum(1 for x in payload[5:105] if 32 <= x < 127)   # 출력 가능한 바이트 수
    f[12] = printable / max(len(payload[5:105]), 1)
    if n >= 1400: f[13] = 1.0
    return f


def _body_fp(body: bytes) -> tuple[float, float]:
    # 본문 HMAC의 첫 두 바이트를 0~1로 정규화
    if not body:
        return 0.0, 0.0
    d = hmac.new(BODY_FP_KEY, body, hashlib.sha256).digest()
    return d[0] / 255.0, d[1] / 255.0

# frontend 요청·응답 특징
def fe_features(payload: bytes) -> np.ndarray:
    f = np.zeros(FEAT_LEN, dtype=np.float32)
    m = _REQ_LINE.match(payload)
    if m:                                            # 요청
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
    if sm:                                           # 응답
        f[1] = 1.0
        code = int(sm.group(1)); f[9 + min(code // 100 - 2, 3)] = 1.0    # 2xx~5xx → 9~12행
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


def _packet_feat(dst_ip: int, dst_port: int, tcp_flags: int, payload: bytes, svc_kind: str, iplen: int = 0):
    if svc_kind == "flow":
        return flow_features(dst_port, tcp_flags, payload, iplen), True
    if dst_port in BLOCKED_PORTS:
        return None, False
    if _is_tls(payload):
        return None, False
    if dst_port == 3306:
        return None, False
    if svc_kind == "frontend":
        if _REQ_LINE.match(payload) or _STATUS_LINE.match(payload):
            return fe_features(payload), True
        return None, False
    if _REQ_LINE.match(payload):
        return http_features(payload), True
    return None, False


def _process_one_pcap(path, pod_ip_int, cap, imgs, sids, sid_offset, svc_kind):
    # PCAP의 pod egress 패킷으로 윈도우 생성
    if not os.path.exists(path):
        return False
    auto = pod_ip_int == "AUTO"; detected = None
    sess_buf = {}
    sess_state = {}
    with open(path, "rb") as f:
        for _ts, buf in dpkt.pcap.Reader(f):
            fi = frame_info(buf)
            if fi is None:
                continue
            sid, sip, dip, dport, tflags, payload, iplen = fi
            if auto and detected is None:
                detected = sip
            gate = detected if auto else pod_ip_int
            if gate is not None and sip != gate:
                continue                              # pod egress만 사용
            feat, keep = _packet_feat(dip, dport, tflags, payload, svc_kind, iplen)
            if not keep:
                continue
            # 유효 패킷의 간격과 최근 윈도우 크기 기록
            stt = sess_state.setdefault(sid, {"last": None, "ring": []})
            _dt = 0.0 if stt["last"] is None else float(_ts - stt["last"])
            stt["last"] = _ts
            _n = (iplen - 40) if iplen >= 40 else len(payload)
            stt["ring"].append(max(_n, 0))
            if len(stt["ring"]) > WIN_SIZE:
                stt["ring"].pop(0)
            feat[18], feat[19] = _temporal(_dt, sum(stt["ring"]))
            b = sess_buf.setdefault(sid, {"buf": [], "count_since_emit": 0})
            b["buf"].append(feat)
            if len(b["buf"]) > WIN_SIZE:
                b["buf"].pop(0)
                b["count_since_emit"] += 1
            if len(b["buf"]) == WIN_SIZE:
                # 첫 윈도우 이후 stride 간격으로 저장
                if b["count_since_emit"] == 0 or b["count_since_emit"] >= STRIDE:
                    imgs.append(np.stack(b["buf"], axis=1).astype(np.float32))
                    sids.append(sid + sid_offset)
                    b["count_since_emit"] = 0
                    if len(imgs) >= cap:
                        return True
    return False


def pcap_to_images(paths, pod_ip, cap, svc_kind, per_round=False):
    pod_ip_int = "AUTO" if pod_ip == "auto" else _ip_to_int(pod_ip)
    imgs, sids = [], []
    if not per_round:
        for p in paths:
            if _process_one_pcap(p, pod_ip_int, cap, imgs, sids, 0, svc_kind):
                break
    else:
        per_cap = max(1, cap // len(paths))
        for r, p in enumerate(paths):
            offset = r * MAX_SESSIONS
            round_cap = min(cap, len(imgs) + per_cap)
            _process_one_pcap(p, pod_ip_int, round_cap, imgs, sids, offset, svc_kind)
            if len(imgs) >= cap:
                break
    if not imgs:
        return np.empty((0, FEAT_LEN, WIN_SIZE), np.float32), np.empty((0,), np.int64)
    return np.stack(imgs), np.asarray(sids, np.int64)


def save(outdir, name, X, sess):
    os.makedirs(outdir, exist_ok=True)
    np.save(os.path.join(outdir, f"X_{name}.npy"), X)
    np.save(os.path.join(outdir, f"sess_{name}.npy"), sess)


def _round_num(p):
    m = re.search(r"round(\d+)", p)
    return int(m.group(1)) if m else 0


def _round_paths(subdir, base):
    # round별 PCAP을 번호순으로 사용
    rounds = sorted(glob.glob(os.path.join(RESULT, subdir, "round*", base + ".pcap")),
                    key=_round_num)
    if rounds:
        return rounds, True
    return [os.path.join(RESULT, subdir, base + ".pcap")], False


def _pod_ip(svc, default):
    return os.environ.get(f"POD_IP_{svc.upper()}", default)


SVC_KIND = {"auth": "flow", "post": "backend", "comment": "backend",
            "frontend": "frontend", "mysql": "flow"}
BENIGN = {svc: (f"benign_{svc}", _pod_ip(svc, "auto")) for svc in SVC_KIND}

# 평가용 공격 시나리오
EW_SCENARIOS = {
    "post":     ["enum_seq", "l2", "l3"],
    "comment":  ["enum_seq", "l2", "l3"],
    "frontend": ["scan_seq", "r1"],
    "auth":     ["cred_enum"],
}
# 참고·시각화용 시나리오
REFERENCE_SCENARIOS = {
    "post":     ["k1", "k2", "e1", "c2"],
    "comment":  ["k1", "k2", "e1", "c2"],
    "auth":     ["k1", "k2", "e1", "c2"],
    "frontend": ["k1", "k2"],
    "mysql":    ["k1", "k2", "e1", "c2"],
}


def main():
    for svc, (base, pod_ip) in BENIGN.items():
        kind = SVC_KIND[svc]; d = os.path.join(OUT, svc)
        bpaths, brounds = _round_paths("benign", base)
        Xb, sb = pcap_to_images(bpaths, pod_ip, CAP_BENIGN, kind, per_round=brounds)
        save(d, "benign", Xb, sb)
        tpaths, trounds = _round_paths(os.path.join("test", "benign"), base)
        Xt, st = pcap_to_images(tpaths, pod_ip, CAP_TEST, kind, per_round=trounds)
        save(d, "testbenign", Xt, st)
        # backend/frontend는 flow 특징도 별도 저장
        if kind != "flow":
            Xbf, sbf = pcap_to_images(bpaths, pod_ip, CAP_BENIGN, "flow", per_round=brounds)
            save(d, "benignflow", Xbf, sbf)
            Xtf, stf = pcap_to_images(tpaths, pod_ip, CAP_TEST, "flow", per_round=trounds)
            save(d, "testbenignflow", Xtf, stf)
        else:
            save(d, "benignflow", Xb, sb)
            save(d, "testbenignflow", Xt, st)

    ad = os.path.join(OUT, "_attack")
    all_scen = {svc: EW_SCENARIOS.get(svc, []) + REFERENCE_SCENARIOS.get(svc, [])
                for svc in set(EW_SCENARIOS) | set(REFERENCE_SCENARIOS)}
    for svc, scens in all_scen.items():
        pod_ip = _pod_ip(svc, "auto")
        FLOW_SCENS = {"k1", "k2", "e1", "c2"}
        for scen in scens:
            kind = "flow" if scen in FLOW_SCENS else SVC_KIND[svc]
            base = f"attack_{svc}_{scen}"
            apaths, arounds = _round_paths(os.path.join("test", "attack"), base)
            if not arounds and not os.path.exists(apaths[0]):
                continue
            Xa, sa = pcap_to_images(apaths, pod_ip, CAP_ATTACK, kind, per_round=arounds)
            if len(Xa) == 0:
                save(ad, base, np.empty((0, FEAT_LEN, WIN_SIZE), np.float32), np.empty((0,), np.int64))
                continue
            save(ad, base, Xa, sa)


if __name__ == "__main__":
    main()
