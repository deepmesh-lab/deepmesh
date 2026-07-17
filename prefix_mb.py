import sys, dpkt

IN, OUT, TARGET_MB = sys.argv[1], sys.argv[2], float(sys.argv[3])
target = int(TARGET_MB * 1024 * 1024)

# 캡처(시간) 순서대로 목표 바이트까지 연속 유지 → 각 세션의 연속 프리픽스 보존(윈도우 유효)
with open(IN, 'rb') as fi, open(OUT, 'wb') as fo:
    r = dpkt.pcap.Reader(fi)
    w = dpkt.pcap.Writer(fo, linktype=r.datalink())
    written = kept = 0
    for ts, buf in r:
        w.writepkt(buf, ts)
        kept += 1
        written += len(buf) + 16      # + pcap 레코드 헤더
        if written >= target:
            break
print(f"kept {kept} packets  ~{written/1048576:.1f} MB")
