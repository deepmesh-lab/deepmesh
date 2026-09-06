package com.deepmesh.dashboard.stream;

import com.deepmesh.dashboard.common.ApiException;
import com.deepmesh.dashboard.stream.dto.StreamEvents;
import com.deepmesh.dashboard.topology.TopologyService;
import com.deepmesh.dashboard.topology.dto.EdgeResponse;
import com.deepmesh.dashboard.topology.dto.NodeResponse;
import com.deepmesh.dashboard.topology.dto.TopologyResponse;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;
import java.util.function.Function;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

/**
 * 토폴로지 변화를 1초 throttle로 흘린다 (명세 2-2).
 *
 * <p>델타는 직전에 보낸 스냅샷과 비교해 만든다. K8s Watch를 직접 걸지 않고 주기 비교를
 * 쓰는 이유는 판정 카운트 변화도 델타 계기이기 때문이다 — Watch로는 그걸 못 잡으니
 * 어차피 주기 비교가 필요하고, 두 경로를 두면 같은 변화가 두 번 나간다.
 */
@Component
@Slf4j
@RequiredArgsConstructor
public class TopologyBroadcaster {

	/**
	 * 델타의 기준선. **집계 구간별로** 따로 들고 있다.
	 *
	 * <p>구간을 하나로 고정하면 화면이 보는 것과 다른 값을 방송하게 된다. 실제로 5m으로
	 * 고정돼 있어, 1시간을 보는 화면에 "최근 5분에는 간선이 없다"는 빈 스냅샷이 덮여
	 * 그래프가 통째로 비었다.
	 */
	private final Map<String, TopologyResponse> lastByRange = new ConcurrentHashMap<>();

	private final TopologyService topologyService;
	private final SseHub hub;

	/**
	 * 연결 직후 보낼 스냅샷. 실패하면 null이고, 호출부가 스냅샷 전송을 건너뛴다.
	 *
	 * @param timeRange 그 구독자가 보고 있는 집계 구간
	 */
	public TopologyResponse snapshot(String timeRange) {
		try {
			TopologyResponse current = topologyService.topology(timeRange, null);
			lastByRange.put(timeRange, current);
			return current;
		} catch (ApiException exc) {
			// K8s에 닿지 못하는 상태. 스트림 자체는 계속 흘러야 하므로 여기서 삼킨다.
			log.debug("토폴로지 스냅샷 생략: {}", exc.getMessage());
			return null;
		}
	}

	/**
	 * 구간별 재계산 주기(틱 수). 이 스케줄이 1초마다 도므로 값이 곧 초다.
	 *
	 * <p>{@code buildEdges}는 구간 안의 판정 이벤트와 benign 집계를 <b>전부</b> 읽는다.
	 * 6시간이면 수만 행이라 매초 다시 읽으면 백엔드가 그 일만 하게 된다. 넓은 구간의
	 * 그림은 1초 사이에 눈에 띄게 변하지 않으므로 주기를 구간에 비례해 늘린다.
	 *
	 * <p>탐지 피드는 이 제한과 무관하다. 그쪽은 DetectionBroadcaster가 200ms로 따로
	 * 흘리므로, 공격이 일어난 순간의 로그는 넓은 구간을 보고 있어도 즉시 도착한다.
	 */
	private static final Map<String, Integer> REFRESH_TICKS = Map.of(
			"1m", 1, "5m", 1, "15m", 1,
			"30m", 2, "1h", 2, "6h", 10, "24h", 30);

	private static final int DEFAULT_REFRESH_TICKS = 2;

	/** publishDelta 호출 횟수. 시계에 기대지 않아 테스트가 결정적이다. */
	private long tick;

	@Scheduled(fixedRate = 1000)
	public void publishDelta() {
		Set<String> ranges = hub.activeTimeRanges();
		if (ranges.isEmpty()) {
			return;
		}
		tick++;
		// 아무도 안 보는 구간의 기준선은 버린다. 다시 붙으면 스냅샷부터 다시 잡는다.
		lastByRange.keySet().retainAll(ranges);

		for (String range : ranges) {
			if (tick % REFRESH_TICKS.getOrDefault(range, DEFAULT_REFRESH_TICKS) != 0) {
				continue;
			}
			TopologyResponse previous = lastByRange.get(range);
			TopologyResponse current;
			try {
				current = topologyService.topology(range, null);
			} catch (ApiException exc) {
				continue;   // 다음 틱에 다시 시도한다
			}
			lastByRange.put(range, current);
			if (previous == null) {
				continue;   // 기준선이 없다. 구독자는 연결 시 스냅샷을 이미 받았다.
			}
			StreamEvents.TopologyDelta delta = diff(previous, current, hub.now());
			if (!delta.isEmpty()) {
				hub.broadcastTo(range, "topology", delta);
			}
		}
	}

	static StreamEvents.TopologyDelta diff(TopologyResponse before, TopologyResponse after,
			java.time.OffsetDateTime sentAt) {
		Map<String, NodeResponse> beforeNodes = index(before.nodes(), NodeResponse::id);
		Map<String, NodeResponse> afterNodes = index(after.nodes(), NodeResponse::id);
		Map<String, EdgeResponse> beforeEdges = index(before.edges(), EdgeResponse::id);
		Map<String, EdgeResponse> afterEdges = index(after.edges(), EdgeResponse::id);

		List<NodeResponse> addedNodes = new ArrayList<>();
		List<NodeResponse> updatedNodes = new ArrayList<>();
		for (NodeResponse node : after.nodes()) {
			NodeResponse old = beforeNodes.get(node.id());
			if (old == null) {
				addedNodes.add(node);
			} else if (!old.equals(node)) {
				updatedNodes.add(node);
			}
		}
		List<EdgeResponse> addedEdges = new ArrayList<>();
		List<EdgeResponse> updatedEdges = new ArrayList<>();
		for (EdgeResponse edge : after.edges()) {
			EdgeResponse old = beforeEdges.get(edge.id());
			if (old == null) {
				// 시나리오 1의 시각적 핵심 — 평소 없던 엣지가 여기로 나간다.
				addedEdges.add(edge);
			} else if (!old.equals(edge)) {
				updatedEdges.add(edge);
			}
		}
		List<String> removedNodeIds = beforeNodes.keySet().stream()
				.filter(id -> !afterNodes.containsKey(id)).toList();
		List<String> removedEdgeIds = beforeEdges.keySet().stream()
				.filter(id -> !afterEdges.containsKey(id)).toList();

		return new StreamEvents.TopologyDelta("TOPOLOGY_DELTA", sentAt,
				updatedNodes, updatedEdges, addedNodes, removedNodeIds, addedEdges, removedEdgeIds);
	}

	private static <T> Map<String, T> index(List<T> items, Function<T, String> key) {
		Map<String, T> out = new LinkedHashMap<>();
		for (T item : items) {
			out.put(key.apply(item), item);
		}
		return out;
	}
}
