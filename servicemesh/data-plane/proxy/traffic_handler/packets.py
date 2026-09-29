# -*- coding: utf-8 -*-
"""판정에 쓰인 윈도우의 패킷 메타데이터.

대시보드 상세 화면이 "이 판정은 어떤 패킷들을 보고 내려졌나"를 보여주려면 모델에
들어간 그 윈도우가 그대로 필요하다. 그래서 메타는 **컨버터가 벡터를 쌓는 자리에서**
같이 쌓는다(detection_binding.ModelConverter). 탐지 경로에서 따로 세면 컨버터가
extract()로 걸러낸 프레임까지 섞여 들어가 실제 판정 윈도우와 어긋난다.

페이로드 본문은 담지 않는다. 길이만 남긴다 — 대시보드로 나가는 값이라 요청·응답
본문이 그대로 흘러나가면 안 된다.
"""

from datetime import datetime, timezone

# TCP 플래그 비트. 낮은 자리부터.
_FLAG_NAMES = (
    (0x01, "FIN"),
    (0x02, "SYN"),
    (0x04, "RST"),
    (0x08, "PSH"),
    (0x10, "ACK"),
    (0x20, "URG"),
    (0x40, "ECE"),
    (0x80, "CWR"),
)


def decode_flags(tcp_flags):
    """플래그 바이트를 "PSH,ACK" 같은 문자열로. 없으면 빈 문자열."""
    names = [name for bit, name in _FLAG_NAMES if tcp_flags & bit]
    return ",".join(names)


def _ip_str(value):
    """frame_info가 주는 32비트 정수 IP를 점표기로. 이미 문자열이면 그대로."""
    if isinstance(value, str):
        return value
    return ".".join(str((value >> shift) & 0xFF) for shift in (24, 16, 8, 0))


def _iso(ts):
    """epoch 초를 로컬 타임존 ISO 문자열로. 이벤트의 occurredAt과 같은 형식이다."""
    return datetime.fromtimestamp(ts, timezone.utc).astimezone().isoformat()


def packet_meta(dst_ip, dst_port, tcp_flags, payload_len, ip_total_len, ts):
    """윈도우에 쌓을 패킷 한 줄.

    seq는 여기서 매기지 않는다. 윈도우는 링버퍼라 오래된 것이 밀려나므로, 판정 시점에
    남아 있는 순서대로 1부터 붙여야 화면의 순번과 모델이 본 순서가 일치한다.
    """
    return {
        "capturedAt": _iso(ts),
        "length": ip_total_len,
        "payloadLength": payload_len,
        "flags": decode_flags(tcp_flags),
        "dstIp": _ip_str(dst_ip),
        "dstPort": dst_port,
    }


def numbered(window):
    """윈도우의 메타에 1부터 순번을 붙여 리스트로 만든다."""
    return [dict(meta, seq=index + 1) for index, meta in enumerate(window)]
