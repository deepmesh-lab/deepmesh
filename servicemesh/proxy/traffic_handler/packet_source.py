# -*- coding: utf-8 -*-
"""PacketSource 구현.

AF_PACKET은 Linux 전용이고 NET_RAW capability가 필요하다. 개발 PC나 단위 테스트에서는
ListPacketSource를 쓴다.
"""

import logging
import socket

logger = logging.getLogger("traffic-handler.packet-source")

ETH_P_ALL = 0x0003


class AfPacketSource:
    """지정 인터페이스의 Ethernet 프레임을 그대로 읽는다."""

    def __init__(self, iface=None, snaplen=65535):
        self._iface = iface
        self._snaplen = snaplen
        self._sock = None
        self._closed = False

    def _open(self):
        sock = socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.htons(ETH_P_ALL))
        if self._iface:
            sock.bind((self._iface, 0))
        sock.settimeout(1.0)
        return sock

    def frames(self):
        self._sock = self._open()
        logger.info("패킷 캡처 시작: iface=%s", self._iface or "any")
        while not self._closed:
            try:
                frame = self._sock.recv(self._snaplen)
            except socket.timeout:
                continue
            except OSError:
                if self._closed:
                    break
                raise
            if frame:
                yield frame

    def close(self):
        self._closed = True
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass


class ListPacketSource:
    """테스트용 — 미리 준비한 프레임을 순서대로 흘린다."""

    def __init__(self, frames):
        self._frames = list(frames)
        self._closed = False

    def frames(self):
        for frame in self._frames:
            if self._closed:
                break
            yield frame

    def close(self):
        self._closed = True
