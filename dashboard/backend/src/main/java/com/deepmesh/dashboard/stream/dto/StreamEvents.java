package com.deepmesh.dashboard.stream.dto;

import com.deepmesh.dashboard.event.dto.EventResponse;
import com.deepmesh.dashboard.topology.dto.EdgeResponse;
import com.deepmesh.dashboard.topology.dto.NodeResponse;
import java.time.OffsetDateTime;
import java.util.List;

/**
 * SSE 페이로드 (backend-frontend-api.md 2-2).
 *
 * <p>각 프레임의 data는 한 줄짜리 JSON이고, event 이름으로 프론트가 분기한다. type 필드는
 * 같은 event 이름 안에서 형태가 갈리는 topology를 위해 있고, 나머지는 일관성을 위해 둔다.
 */
public final class StreamEvents {

	private StreamEvents() {
	}

	/**
	 * benign·cleared·drop·relay 네 분류가 모두 들어온다. 전체 트래픽 규모는 stats가
	 * 나른다.
	 *
	 * <p>SSE id는 이 배치의 최대 eventId다. 페이로드에 latestEventId를 따로 넣지 않는다 —
	 * 프로토콜 필드가 그 역할을 하므로 중복이다.
	 */
	public record DetectionBatch(
			String type, OffsetDateTime sentAt, List<EventResponse> events, int droppedCount) {

		public static DetectionBatch of(OffsetDateTime sentAt, List<EventResponse> events, int dropped) {
			return new DetectionBatch("DETECTION_BATCH", sentAt, events, dropped);
		}
	}

	/**
	 * 연결 직후 1회. 최초 연결과 재연결 모두에서 보낸다 — 토폴로지는 델타를 소급 적용할 수
	 * 없어 단절 구간 이후의 누적 상태를 신뢰할 수 없다. 프론트는 이걸 받으면 기존 상태를
	 * 병합이 아니라 교체한다.
	 */
	public record TopologySnapshot(
			String type, OffsetDateTime sentAt, List<NodeResponse> nodes, List<EdgeResponse> edges) {

		public static TopologySnapshot of(OffsetDateTime sentAt,
				List<NodeResponse> nodes, List<EdgeResponse> edges) {
			return new TopologySnapshot("TOPOLOGY_SNAPSHOT", sentAt, nodes, edges);
		}
	}

	/**
	 * 변화분. updated*는 부분 객체가 아니라 완전 객체를 보낸다 — 프론트가 merge하므로
	 * 결과는 같고, 어떤 필드가 바뀌었는지 서버가 추적하지 않아도 된다.
	 */
	public record TopologyDelta(
			String type, OffsetDateTime sentAt,
			List<NodeResponse> updatedNodes, List<EdgeResponse> updatedEdges,
			List<NodeResponse> addedNodes, List<String> removedNodeIds,
			List<EdgeResponse> addedEdges, List<String> removedEdgeIds) {

		public boolean isEmpty() {
			return updatedNodes.isEmpty() && updatedEdges.isEmpty()
					&& addedNodes.isEmpty() && removedNodeIds.isEmpty()
					&& addedEdges.isEmpty() && removedEdgeIds.isEmpty();
		}
	}

	/**
	 * 1초 고정 주기. 이벤트가 0건이어도 보내며, 프론트가 연결 생존 신호로도 쓴다.
	 *
	 * <p>p95는 담지 않는다 — 1초 주기로 백분위수를 내면 표본이 부족해 값이 심하게 흔들린다.
	 */
	public record StatsTick(
			String type, OffsetDateTime ts, String timeRange,
			long totalSequences, long benignCount, long clearedCount,
			long dropCount, long relayCount,
			double anomalyRate, double blockRate, Double avgDetectionLatencyMs) {
	}

	/**
	 * DROP·RELAY에만 발행한다. cleared는 서비스에 영향이 없었고 시스템이 의도대로 동작한
	 * 결과여서 알림 피로만 유발한다 — 이력에는 남는다.
	 */
	public record Alert(
			String type, String severity, String eventId, OffsetDateTime occurredAt,
			String verdict, String serviceName, String podName, String title, String message) {
	}

	/** 재전송 상한을 넘겨 잘린 구간. 프론트는 "n건 생략" 후 이력 조회로 안내한다. */
	public record ReplayTruncated(String type, int missedCount, OffsetDateTime since) {

		public static ReplayTruncated of(int missedCount, OffsetDateTime since) {
			return new ReplayTruncated("REPLAY_TRUNCATED", missedCount, since);
		}
	}
}
