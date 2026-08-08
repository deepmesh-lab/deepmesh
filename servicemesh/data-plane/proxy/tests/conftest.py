# -*- coding: utf-8 -*-
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def make_frame(src_ip, dst_ip, src_port, dst_port, payload=b"", proto=6):
    """테스트용 Ethernet/IPv4/TCP 프레임을 만든다."""
    def ip_bytes(ip):
        return bytes(int(x) for x in ip.split("."))

    tcp = struct.pack("!HHIIBBHHH", src_port, dst_port, 0, 0, 5 << 4, 0x18, 0, 0, 0) + payload
    total_length = 20 + len(tcp)
    ip = struct.pack(
        "!BBHHHBBH4s4s",
        0x45, 0, total_length, 0, 0, 64, proto, 0, ip_bytes(src_ip), ip_bytes(dst_ip),
    )
    ethernet = b"\x00" * 12 + struct.pack("!H", 0x0800)
    return ethernet + ip + tcp
