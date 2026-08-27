package com.deepmesh.dashboard.topology;

import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Index;
import jakarta.persistence.Table;
import java.time.OffsetDateTime;
import lombok.AccessLevel;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Getter;
import lombok.NoArgsConstructor;

/**
 * 프록시가 1초 주기로 보내는 peerStats 한 줄 — 목적지별 benign 집계.
 *
 * <p>토폴로지의 평시 엣지는 이것만이 근거다. cleared/drop/relay는 detection_event가
 * dstIp와 함께 갖고 있지만 benign은 개별 이벤트로 남지 않아, 이 표가 없으면 정상 통신
 * 경로가 그래프에 그려지지 않는다 (TELEMETRY_API.md의 peerStats 절).
 *
 * <p>stats_bucket과 나눈 이유는 집계 단위가 다르기 때문이다. stats_bucket은 프록시 단위
 * 4분류이고 /dashboard/stats/*가 쓰는 반면, 이쪽은 (프록시, 목적지) 단위 benign 하나이며
 * 토폴로지 엣지만 쓴다. 한 표에 합치면 목적지 없는 행과 있는 행이 섞여 두 집계가 서로를
 * 오염시킨다.
 */
@Entity
@Table(name = "peer_benign_bucket", indexes = {
		@Index(name = "idx_peer_service_to", columnList = "serviceName, windowTo")
})
@Getter
@NoArgsConstructor(access = AccessLevel.PROTECTED)
@AllArgsConstructor(access = AccessLevel.PRIVATE)
@Builder
public class PeerBenignBucket {

	@Id
	@GeneratedValue(strategy = GenerationType.IDENTITY)
	private Long id;

	/** 관측 주체. 엣지의 source다. */
	private String serviceName;
	private String podName;

	/** 목적지 IP. 프록시 슬롯 상한에 걸려 접힌 몫은 "other"로 온다. */
	private String dstIp;

	private OffsetDateTime windowFrom;
	private OffsetDateTime windowTo;

	private long benign;

	/**
	 * 그 창에서 관측한 서로 다른 목적지 수. 행마다 같은 값이 들어간다(창 단위 값이라
	 * 중복이지만, 별도 표를 두면 조인 없이는 못 읽는다).
	 *
	 * <p>슬롯 상한에 걸려 other로 접힌 목적지까지 세므로, 평시 10에서 갑자기 수천이
	 * 되는 것이 스캔 신호다.
	 */
	private int peerCount;
}
