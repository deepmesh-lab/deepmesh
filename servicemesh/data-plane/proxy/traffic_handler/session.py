# -*- coding: utf-8 -*-
"""Ethernet 프레임에서 세션 정보를 뽑고, 메인 컨테이너 트래픽인지 판별한다."""

import struct

from .ports import IPPROTO_TCP, SessionKey

ETH_HDR_LEN = 14
ETHERTYPE_IPV4 = 0x0800


def parse_session(frame):
    """IPv4/TCP 프레임에서 SessionKey를 만든다. 아니면 None.

    loopback(lo)도 14바이트 유사 Ethernet 헤더를 달고 오므로 같은 방식으로 파싱된다.
    """
    if len(frame) < ETH_HDR_LEN + 20 + 20:
        return None
    if struct.unpack("!H", frame[12:14])[0] != ETHERTYPE_IPV4:
        return None

    ip = frame[ETH_HDR_LEN:]
    if (ip[0] >> 4) != 4:
        return None
    ihl = (ip[0] & 0x0F) * 4
    if ihl < 20 or ip[9] != IPPROTO_TCP or len(ip) < ihl + 4:
        return None

    src_ip = ".".join(str(b) for b in ip[12:16])
    dst_ip = ".".join(str(b) for b in ip[16:20])
    src_port, dst_port = struct.unpack("!HH", ip[ihl:ihl + 4])
    return SessionKey(src_ip, dst_ip, src_port, dst_port, IPPROTO_TCP)


def is_from_main_container(key, target_port, proxy_port):
    """이 세션의 트래픽이 메인 컨테이너에서 나온 것인가 (= 논문의 T_main).

    프록시는 loopback에서 메인 컨테이너와 마주 본다. 두 방향을 포트로 구분한다.

        메인 → 프록시
          · outbound 요청: iptables OUTPUT REDIRECT를 타고 dst_port == PROXY_PORT
          · outbound 응답: 메인이 서버이므로 src_port == TARGET_PORT
        프록시 → 메인 (탐지 대상 아님)
          · 요청 전달: dst_port == TARGET_PORT
          · 응답 전달: src_port == PROXY_PORT

    inbound(외부 → 우리 Pod)는 탐지 대상이 아니므로 여기서 걸러진다. 위협 모델이
    lateral movement라 침해된 Pod에서 '나가는' 트래픽만 검사한다.
    """
    return key.dst_port == proxy_port or key.src_port == target_port
