package com.deepmesh.dashboard.event.dto;

import com.deepmesh.dashboard.event.DetectionEvent;
import java.time.OffsetDateTime;

/**
 * backend-frontend-api.md 1-7 이벤트 목록 행.
 *
 * <p>eventId는 문자열로 직렬화한다 — JS Number 안전 정수 상한을 넘으면 정밀도가 손실된다.
 */
public record EventResponse(
		String eventId,
		OffsetDateTime occurredAt,
		String serviceName,
		String podName,
		String namespace,
		String nodeName,
		String direction,
		String sessionId,
		String srcIp,
		Integer srcPort,
		String dstIp,
		Integer dstPort,
		String protocol,
		String peerServiceName,
		String modelVerdict,
		Double ocsvmScore,
		String verdict,
		String category,
		String verificationStage,
		Boolean verificationPassed,
		Double detectionLatencyMs,
		String summary
) {
	public static EventResponse from(DetectionEvent e) {
		return new EventResponse(
				String.valueOf(e.getEventId()), e.getOccurredAt(), e.getServiceName(),
				e.getPodName(), e.getNamespace(), e.getNodeName(), e.getDirection(),
				e.getSessionId(), e.getSrcIp(), e.getSrcPort(), e.getDstIp(), e.getDstPort(),
				e.getProtocol(), e.getPeerServiceName(), e.getModelVerdict(), e.getOcsvmScore(),
				e.getVerdict(), e.getCategory(), e.getVerificationStage(),
				e.getVerificationPassed(), e.getDetectionLatencyMs(), e.getSummary());
	}
}
