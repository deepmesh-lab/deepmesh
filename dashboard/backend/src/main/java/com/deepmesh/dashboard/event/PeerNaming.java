package com.deepmesh.dashboard.event;

import com.deepmesh.dashboard.event.dto.EventResponse;
import com.deepmesh.dashboard.topology.ClusterTopologySource;
import com.deepmesh.dashboard.topology.PeerIndex;
import java.util.List;
import lombok.RequiredArgsConstructor;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

/**
 * 이벤트의 목적지 IP를 서비스 이름으로 되돌린다.
 *
 * <p>프록시는 IP만 보낸다(TELEMETRY_API.md 필드 담당 경계) — 역매핑에 필요한 K8s 지식을
 * 사이드카에 두면 사이드카가 K8s API를 호출하게 되고, 그 호출이 다시 자기 탐지 대상이
 * 된다. 그래서 백엔드가 이름을 붙인다.
 *
 * <p><b>수집 시점이 아니라 조회 시점에 되돌리는 이유</b>: 저장할 때 채워 굳히면 그 순간
 * 캐시에 없던 IP가 영구히 null로 남는다. Pod IP는 재배포마다 바뀌므로 그 창이 실제로
 * 열린다.
 *
 * <p>REST 목록·상세와 SSE(재전송·라이브 배치)가 모두 같은 규칙을 써야 화면에서 이름이
 * 들쭉날쭉하지 않는다. 그래서 한 곳에 모았다.
 */
@Component
@RequiredArgsConstructor
public class PeerNaming {

	private final ClusterTopologySource cluster;

	@Value("${deepmesh.namespace:deepmesh}")
	private String namespace;

	public List<EventResponse> name(List<DetectionEvent> events) {
		PeerIndex peers = index();
		return events.stream().map(e -> name(e, peers)).toList();
	}

	public EventResponse name(DetectionEvent event) {
		return name(event, index());
	}

	private static EventResponse name(DetectionEvent event, PeerIndex peers) {
		return EventResponse.from(event, peers.resolve(event.getDstIp(), event.getDstPort()));
	}

	/**
	 * K8s에 닿지 못하면 빈 색인을 쓴다 — 이름이 안 붙을 뿐, 이벤트 조회 자체는 K8s와
	 * 무관하게 동작해야 한다.
	 */
	public PeerIndex index() {
		try {
			return cluster.peerIndex(namespace);
		} catch (Exception exc) {
			return PeerIndex.empty();
		}
	}
}
