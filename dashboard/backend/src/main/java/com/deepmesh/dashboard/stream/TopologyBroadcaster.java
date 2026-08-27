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

	/** 델타의 기준선. 스냅샷을 보낼 때마다 갱신된다. */
	private volatile TopologyResponse last;

	private final TopologyService topologyService;
	private final SseHub hub;

	/** 연결 직후 보낼 스냅샷. 실패하면 null이고, 호출부가 스냅샷 전송을 건너뛴다. */
	public TopologyResponse snapshot() {
		try {
			TopologyResponse current = topologyService.topology("5m", null);
			last = current;
			return current;
		} catch (ApiException exc) {
			// K8s에 닿지 못하는 상태. 스트림 자체는 계속 흘러야 하므로 여기서 삼킨다.
			log.debug("토폴로지 스냅샷 생략: {}", exc.getMessage());
			return null;
		}
	}

	@Scheduled(fixedRate = 1000)
	public void publishDelta() {
		if (hub.subscriberCount() == 0) {
			return;
		}
		TopologyResponse previous = last;
		TopologyResponse current;
		try {
			current = topologyService.topology("5m", null);
		} catch (ApiException exc) {
			return;   // 다음 틱에 다시 시도한다
		}
		last = current;
		if (previous == null) {
			return;   // 기준선이 없다. 구독자는 연결 시 스냅샷을 이미 받았다.
		}
		StreamEvents.TopologyDelta delta = diff(previous, current, hub.now());
		if (!delta.isEmpty()) {
			hub.broadcast("topology", delta);
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
