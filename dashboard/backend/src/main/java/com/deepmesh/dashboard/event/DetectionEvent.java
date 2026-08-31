package com.deepmesh.dashboard.event;

import jakarta.persistence.Column;
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
 * 프록시가 ATTACK으로 판정한 개별 시퀀스(cleared/drop/relay).
 *
 * <p>필드는 backend-frontend-api.md의 이벤트 스키마를 따른다. 프록시가 보내는 값은
 * TELEMETRY_API.md 계약에서 오며, 백엔드가 채우는 값(peerServiceName, summary)은
 * 저장 시점 또는 이후에 채운다. eventId는 시간 단조 증가하는 BIGINT로 커서로도 쓰인다.
 */
@Entity
@Table(name = "detection_event", indexes = {
		@Index(name = "idx_event_service", columnList = "serviceName"),
		@Index(name = "idx_event_occurred", columnList = "occurredAt")
})
@Getter
@NoArgsConstructor(access = AccessLevel.PROTECTED)
@AllArgsConstructor(access = AccessLevel.PRIVATE)
@Builder
public class DetectionEvent {

	@Id
	@GeneratedValue(strategy = GenerationType.IDENTITY)
	private Long eventId;

	// --- 프록시 출처 (배치의 proxy 블록에서 복사) ---
	private String serviceName;
	private String podName;
	private String namespace;
	private String nodeName;

	// --- 판정 시점 관측 ---
	private OffsetDateTime occurredAt;
	private String direction;          // REQUEST | RESPONSE
	private String sessionId;
	private String srcIp;
	private Integer srcPort;
	private String dstIp;
	private Integer dstPort;
	private String protocol;

	// --- 모델 판정 ---
	private String modelVerdict;       // ATTACK (이 테이블은 ATTACK만 저장)
	private Double ocsvmScore;
	private Double detectionLatencyMs;

	// --- 집행 결과 ---
	private String verdict;            // FORWARD | DROP | RELAY
	private String category;           // cleared | drop | relay
	private String verificationStage;  // REQUEST_VERIFIER | RESPONSE_CONSISTENCY
	private Boolean verificationPassed;

	@Column(length = 512)
	private String signature;

	// --- 백엔드가 채우는 필드 ---
	private String peerServiceName;    // K8s watch 역매핑 (미구현 시 null)

	@Column(length = 512)
	private String summary;            // category+signature 기반 한국어 요약

	// --- 상세 조회용 (Converter 결합 시 채워짐) ---
	private Integer windowSize;
	private String modelId;

	@Column(columnDefinition = "TEXT")
	private String packetsJson;        // 윈도우 패킷 메타 JSON. 없으면 null

	/** 백엔드가 나중에 K8s 역매핑으로 채운다. */
	public void assignPeerServiceName(String peerServiceName) {
		this.peerServiceName = peerServiceName;
	}
}
