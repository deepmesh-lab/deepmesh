package com.deepmesh.dashboard.ingest;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.deepmesh.dashboard.event.DetectionEvent;
import com.deepmesh.dashboard.event.DetectionEventRepository;
import com.deepmesh.dashboard.ingest.dto.IngestRequest;
import com.deepmesh.dashboard.stats.StatsBucket;
import com.deepmesh.dashboard.stats.StatsBucketRepository;
import java.util.ArrayList;
import java.util.List;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/**
 * 프록시 수집 배치를 저장한다.
 *
 * <p>events는 개별 저장, windowStats는 집계 한 건으로 저장한다. peerServiceName은
 * K8s 역매핑(미구현) 전까지 null이며, summary는 category+signature로 여기서 생성한다.
 */
@Service
@Slf4j
@RequiredArgsConstructor
public class IngestService {

	private final DetectionEventRepository eventRepository;
	private final StatsBucketRepository statsRepository;
	private final ObjectMapper objectMapper;

	@Transactional
	public int ingest(IngestRequest request) {
		IngestRequest.Proxy proxy = request.getProxy();

		if (request.getWindowStats() != null) {
			statsRepository.save(toBucket(proxy, request.getWindowStats()));
		}

		List<DetectionEvent> saved = new ArrayList<>();
		if (request.getEvents() != null) {
			for (IngestRequest.Event event : request.getEvents()) {
				saved.add(toEntity(proxy, event));
			}
			eventRepository.saveAll(saved);
		}
		return saved.size();
	}

	private StatsBucket toBucket(IngestRequest.Proxy proxy, IngestRequest.WindowStats stats) {
		return StatsBucket.builder()
				.serviceName(proxy.getServiceName())
				.podName(proxy.getPodName())
				.windowFrom(stats.getFrom())
				.windowTo(stats.getTo())
				.benign(stats.getBenign())
				.cleared(stats.getCleared())
				.drop(stats.getDrop())
				.relay(stats.getRelay())
				.build();
	}

	private DetectionEvent toEntity(IngestRequest.Proxy proxy, IngestRequest.Event event) {
		return DetectionEvent.builder()
				.serviceName(proxy.getServiceName())
				.podName(proxy.getPodName())
				.namespace(proxy.getNamespace())
				.nodeName(proxy.getNodeName())
				.occurredAt(event.getOccurredAt())
				.direction(event.getDirection())
				.sessionId(event.getSessionId())
				.srcIp(event.getSrcIp())
				.srcPort(event.getSrcPort())
				.dstIp(event.getDstIp())
				.dstPort(event.getDstPort())
				.protocol(event.getProtocol())
				.modelVerdict(event.getModelVerdict())
				.ocsvmScore(event.getOcsvmScore())
				.detectionLatencyMs(event.getDetectionLatencyMs())
				.verdict(event.getVerdict())
				.category(event.getCategory())
				.verificationStage(event.getVerificationStage())
				.verificationPassed(event.getVerificationPassed())
				.signature(event.getSignature())
				.windowSize(event.getWindowSize())
				.modelId(event.getModelId())
				.packetsJson(serializePackets(event.getPackets()))
				.peerServiceName(null)   // K8s 역매핑 결합 시 채움
				.summary(buildSummary(event))
				.build();
	}

	private String serializePackets(JsonNode packets) {
		if (packets == null || packets.isNull()) {
			return null;
		}
		try {
			return objectMapper.writeValueAsString(packets);
		} catch (JsonProcessingException exc) {
			log.warn("packets 직렬화 실패 — null로 저장: {}", exc.getMessage());
			return null;
		}
	}

	/** 화면 표시용 한 줄 요약. K8s 역매핑이 붙으면 목적지 이름까지 반영하도록 확장한다. */
	private String buildSummary(IngestRequest.Event event) {
		String sig = event.getSignature() == null ? "" : event.getSignature();
		return switch (event.getCategory() == null ? "" : event.getCategory()) {
			case "drop" -> "미관측 요청 차단 — " + sig;
			case "relay" -> "응답 변조 탐지·교체 — " + sig;
			case "cleared" -> "이상 판정 후 교차 검증 통과 — " + sig;
			default -> sig;
		};
	}
}
