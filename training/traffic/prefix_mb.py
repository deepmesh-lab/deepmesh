import sys, dpkt

# 인자: 입력, 출력, 크기(MB)
IN, OUT, TARGET_MB = sys.argv[1], sys.argv[2], float(sys.argv[3])
target = int(TARGET_MB * 1024 * 1024)

# 앞에서부터 목표 크기까지 저장.
with open(IN, 'rb') as fi, open(OUT, 'wb') as fo:
    r = dpkt.pcap.Reader(fi)
    w = dpkt.pcap.Writer(fo, linktype=r.datalink())
    written = kept = 0
    for ts, buf in r:
        w.writepkt(buf, ts)
        kept += 1
        written += len(buf) + 16
        if written >= target:
            break
print(f"kept {kept} packets  ~{written/1048576:.1f} MB")
