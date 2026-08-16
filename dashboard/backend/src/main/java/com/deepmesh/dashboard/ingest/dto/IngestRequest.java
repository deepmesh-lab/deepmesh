package com.deepmesh.dashboard.ingest.dto;

import com.fasterxml.jackson.databind.JsonNode;
import jakarta.validation.Valid;
import jakarta.validation.constraints.NotNull;
import java.time.OffsetDateTime;
import java.util.List;
import lombok.Getter;
import lombok.Setter;

/**
 * 프록시 → 백엔드 수집 페이로드 (TELEMETRY_API.md).
 *
 * <p>한 배치는 발신 프록시 정보(proxy), 구간 집계(windowStats), 개별 이벤트(events)로
 * 이루어진다. events는 비어 있을 수 있다(정상 트래픽만 흐른 구간).
 */
@Getter
@Setter
public class IngestRequest {

	@NotNull
	@Valid
	private Proxy proxy;

	@Valid
	private WindowStats windowStats;

	@Valid
	private List<Event> events;

	@Getter
	@Setter
	public static class Proxy {
		@NotNull
		private String serviceName;
		private String podName;
		private String podIp;
		private String nodeName;
		private String namespace;
	}

	@Getter
	@Setter
	public static class WindowStats {
		private OffsetDateTime from;
		private OffsetDateTime to;
		private long benign;
		private long cleared;
		private long drop;
		private long relay;
	}

	@Getter
	@Setter
	public static class Event {
		private OffsetDateTime occurredAt;
		private String direction;
		private String sessionId;
		private String srcIp;
		private Integer srcPort;
		private String dstIp;
		private Integer dstPort;
		private String protocol;
		private String modelVerdict;
		private Double ocsvmScore;
		private String verdict;
		private String category;
		private String verificationStage;
		private Boolean verificationPassed;
		private Double detectionLatencyMs;
		private String signature;
		private Integer windowSize;
		private String modelId;
		private JsonNode packets;   // 윈도우 패킷 메타. 없으면 null
	}
}
