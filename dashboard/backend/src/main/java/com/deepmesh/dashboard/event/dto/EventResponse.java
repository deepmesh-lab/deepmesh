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
		return from(e, e.getPeerServiceName());
	}

	/**
	 * 목적지 이름을 조회 시점에 역매핑해 넣는다.
	 *
	 * <p>수집 때는 프록시가 IP만 보내므로(TELEMETRY_API.md 필드 담당 경계)
	 * peerServiceName이 비어 있다. 저장 시점에 채워 굳히면 그때 캐시에 없던 IP가 영구히
	 * null로 남고, Pod IP는 재배포마다 바뀌어 그 창이 실제로 열린다. 그래서 토폴로지와
	 * 같은 PeerIndex로 여기서 되돌린다 — 안 하면 화면에 "알 수 없음"으로 뜬다.
	 */
	public static EventResponse from(DetectionEvent e, String peerServiceName) {
		return new EventResponse(
				String.valueOf(e.getEventId()), e.getOccurredAt(), e.getServiceName(),
				e.getPodName(), e.getNamespace(), e.getNodeName(), e.getDirection(),
				e.getSessionId(), e.getSrcIp(), e.getSrcPort(), e.getDstIp(), e.getDstPort(),
				e.getProtocol(), peerServiceName, e.getModelVerdict(), e.getOcsvmScore(),
				e.getVerdict(), e.getCategory(), e.getVerificationStage(),
				e.getVerificationPassed(), e.getDetectionLatencyMs(), e.getSummary());
	}
}
