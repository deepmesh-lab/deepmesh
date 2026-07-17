import sys, zlib, dpkt

IN, OUT, KEEP = sys.argv[1], sys.argv[2], int(sys.argv[3])   # 세션의 1/KEEP 만 유지


def skey(ip):
    # 양방향을 같은 세션으로 취급하는 5-tuple 키 (IP/포트 정렬)
    a = (ip.src, getattr(ip.data, 'sport', 0))
    b = (ip.dst, getattr(ip.data, 'dport', 0))
    lo, hi = sorted([a, b])
    return lo[0] + hi[0] + bytes([lo[1] >> 8, lo[1] & 255, hi[1] >> 8, hi[1] & 255])


with open(IN, 'rb') as fi, open(OUT, 'wb') as fo:
    r = dpkt.pcap.Reader(fi)
    w = dpkt.pcap.Writer(fo, linktype=r.datalink())   # 원본과 동일 링크계층(Ethernet)
    kept = tot = 0
    for ts, buf in r:
        tot += 1
        try:
            ip = dpkt.ethernet.Ethernet(buf).data
            if not isinstance(ip, dpkt.ip.IP):
                continue
            if zlib.crc32(skey(ip)) % KEEP == 0:          # 세션 단위 결정적 샘플
                w.writepkt(buf, ts)
                kept += 1
        except Exception:
            continue
print(f"kept {kept}/{tot} packets  (KEEP=1/{KEEP})")
