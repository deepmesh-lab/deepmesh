/*
 * packet_parser_stack.c
 *
 * 논문 "Lightweight Service Mesh for Intrusion Detection using KD-CNN" 의
 * Traffic Converter 를 이식한 C 파서.
 *
 * 원본: ServiceMesh/DataPlane/Proxy/packet_parser_stack.c
 * 규칙(논문 §4.2, §5.3):
 *   - 각 패킷을 (19B 프로토콜 헤더필드 + PAYLOAD_LEN B payload) = VEC_LEN 벡터로 변환
 *   - IP 주소/포트 등 가변 필드는 제외(세션 식별에만 사용, 이미지에는 미포함)
 *   - 세션(5-tuple)별로 최근 WIN_SIZE(=5) 패킷을 슬라이딩 윈도우로 쌓아
 *     (VEC_LEN, WIN_SIZE) 로 transpose 하여 grayscale 시퀀스 이미지 생성
 *
 * ── resize(정보밀도) 아이디어 반영 ────────────────────────────────────────
 *   payload 길이를 컴파일타임 매크로로 파라미터화한다. 기본값은 논문과 동일한 1460.
 *   게시판 트래픽처럼 payload 가 짧아 0패딩이 과도할 때, 실제 분포에 맞춰
 *     gcc ... -DPAYLOAD_LEN=512 ...
 *   로 축소해 재컴파일하면 정보밀도를 높일 수 있다.
 *   ※ 이 값을 바꾸면 VEC_LEN 이 바뀌므로 학습 모델 입력 H 차원도 반드시 함께 재학습해야 한다.
 *     (원본 동봉 모델 student_encoder_1x8_ts.pt 는 VEC_LEN=1479 전제 → 그대로 쓰려면 기본값 유지)
 *   학습(preprocess)·추론(proxy)이 동일 .so 를 공유하면 패딩 규칙이 100% 일치한다.
 */
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

#define MAX_SESSIONS 65536
#define WIN_SIZE 5
#define HEADER_LEN 19

#ifndef PAYLOAD_LEN
#define PAYLOAD_LEN 1460          /* 논문 기본값. -DPAYLOAD_LEN=N 으로 재정의 가능 */
#endif

#define VEC_LEN (HEADER_LEN + PAYLOAD_LEN)

typedef struct {
    float buffer[WIN_SIZE][VEC_LEN];
    int count;
} Session;

static Session** session_table = NULL;

/* 파이썬(ctypes)에서 컴파일된 상수를 조회해 텐서 shape 를 자동 정합시키기 위한 getter */
int get_vec_len()   { return VEC_LEN; }
int get_win_size()  { return WIN_SIZE; }
int get_header_len() { return HEADER_LEN; }
int get_payload_len() { return PAYLOAD_LEN; }
int get_max_sessions() { return MAX_SESSIONS; }

int init_session_storage() {
    session_table = (Session**)calloc(MAX_SESSIONS, sizeof(Session*));
    return (session_table != NULL) ? 0 : -1;
}

Session* get_or_create_session(uint32_t session_id) {
    if (session_id >= MAX_SESSIONS) return NULL;
    if (session_table[session_id] == NULL) {
        session_table[session_id] = (Session*)malloc(sizeof(Session));
        if (!session_table[session_id]) return NULL;
        memset(session_table[session_id], 0, sizeof(Session));
    }
    return session_table[session_id];
}

/* 세션 버퍼 명시적 초기화(연결 종료/타임아웃 시 stale 버퍼 재사용 방지용) */
int reset_session(uint32_t session_id) {
    if (session_id >= MAX_SESSIONS) return -1;
    if (session_table && session_table[session_id]) {
        memset(session_table[session_id], 0, sizeof(Session));
    }
    return 0;
}

/*
 * Ethernet 프레임(offset 0 = Ethernet, 14 = IP, 34 = TCP) 하나를 VEC_LEN 벡터로.
 * raw 는 완전한 L2 프레임이어야 한다(AF_PACKET SOCK_RAW 캡처 결과).
 */
int parse_tcp_packet(const uint8_t* raw, size_t len, float* out_vec) {
    if (len < 54) return -1;

    uint8_t ttl = raw[22];
    uint8_t proto = raw[23];
    uint16_t flags_frag = (raw[20] << 8) | raw[21];
    uint8_t ip_flags = (flags_frag >> 13) & 0x7;
    uint16_t frag_offset = flags_frag & 0x1FFF;

    int tcp_off = 14 + 20;
    if (len < tcp_off + 20) return -1;

    uint8_t data_offset = (raw[tcp_off + 12] >> 4) & 0xF;
    uint8_t flags = raw[tcp_off + 13];
    uint16_t window = (raw[tcp_off + 14] << 8) | raw[tcp_off + 15];
    uint16_t urgptr = (raw[tcp_off + 18] << 8) | raw[tcp_off + 19];

    const uint8_t* seq = &raw[tcp_off + 4];
    const uint8_t* ack = &raw[tcp_off + 8];

    int payload_start = tcp_off + data_offset * 4;
    const uint8_t* payload = (payload_start < (int)len) ? &raw[payload_start] : NULL;
    int payload_len = (payload != NULL) ? (int)(len - payload_start) : 0;

    int idx = 0;
    out_vec[idx++] = ttl;                       /* 1  */
    out_vec[idx++] = proto;                     /* 2  */
    out_vec[idx++] = ip_flags;                  /* 3  */
    out_vec[idx++] = (frag_offset >> 8) & 0xFF; /* 4  */
    out_vec[idx++] = frag_offset & 0xFF;        /* 5  */
    out_vec[idx++] = data_offset;               /* 6  */
    out_vec[idx++] = flags;                     /* 7  */
    out_vec[idx++] = (window >> 8) & 0xFF;      /* 8  */
    out_vec[idx++] = window & 0xFF;             /* 9  */
    out_vec[idx++] = (urgptr >> 8) & 0xFF;      /* 10 */
    out_vec[idx++] = urgptr & 0xFF;             /* 11 */

    for (int i = 0; i < 4; ++i) out_vec[idx++] = seq[i];  /* 12~15 */
    for (int i = 0; i < 4; ++i) out_vec[idx++] = ack[i];  /* 16~19 */

    for (int i = 0; i < PAYLOAD_LEN; ++i) {
        out_vec[idx++] = (i < payload_len) ? payload[i] : 0;
    }

    return 0;
}

/*
 * 세션 버퍼에 프레임을 누적하고, WIN_SIZE 개가 차면 (VEC_LEN, WIN_SIZE) 이미지를 out_stack 에 채운다.
 * 반환:  1 = 이미지 완성(out_stack 유효),  0 = 아직 미충족,  -1 = 파싱 실패/에러
 */
int parse_and_stack(const uint8_t* raw, size_t len, float* out_stack, uint32_t session_id) {
    if (session_id >= MAX_SESSIONS) return -1;

    Session* sess = get_or_create_session(session_id);
    if (!sess) return -1;

    float temp[VEC_LEN];
    if (parse_tcp_packet(raw, len, temp) != 0) return -1;

    int idx = sess->count;
    if (idx >= WIN_SIZE) {
        memmove(sess->buffer[0], sess->buffer[1], sizeof(float) * VEC_LEN * (WIN_SIZE - 1));
        idx = WIN_SIZE - 1;
    }

    memcpy(sess->buffer[idx], temp, sizeof(float) * VEC_LEN);
    sess->count = idx + 1;

    if (sess->count < WIN_SIZE) return 0;

    for (int i = 0; i < VEC_LEN; ++i) {
        for (int j = 0; j < WIN_SIZE; ++j) {
            out_stack[i * WIN_SIZE + j] = sess->buffer[j][i];  /* transpose → (VEC_LEN, WIN_SIZE) */
        }
    }

    return 1;
}
