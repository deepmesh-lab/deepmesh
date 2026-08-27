package com.deepmesh.dashboard.topology;

import java.util.Map;

/**
 * 목적지 IP를 토폴로지 노드로 되돌린다. 엣지의 target이 이 결과다.
 *
 * <p>프록시는 IP만 보낸다 — 역매핑에 필요한 K8s 지식을 사이드카에 두면 사이드카가 K8s
 * API를 호출해야 하고, 그 호출이 다시 자기 탐지 대상이 된다 (TELEMETRY_API.md 필드 담당
 * 경계). 그래서 백엔드가 조회 시점에 되돌린다.
 *
 * <p><b>수집 시점이 아니라 조회 시점에 되돌리는 이유</b>: 수집 때 채워 굳히면, 그 순간
 * 캐시에 없던 IP가 영구히 null로 남는다. Pod IP는 재배포마다 바뀌므로 그 창이 실제로
 * 열린다.
 */
public record PeerIndex(
		/** Pod IP·ClusterIP -> 서비스명. */
		Map<String, String> ipToService,
		/** 서비스명 -> 노드 종류. */
		Map<String, NodeKind> serviceKinds,
		/** K8s API Server의 ClusterIP. 보통 kubernetes 서비스의 것. */
		String apiServerIp) {

	/** 알 수 없는 목적지를 접어 넣는 합성 노드 (backend-frontend-api.md의 EXTERNAL). */
	public static final String EXTERNAL_NODE = "external";
	public static final String K8S_API_NODE = "kubernetes";

	public static PeerIndex empty() {
		return new PeerIndex(Map.of(), Map.of(), null);
	}

	/**
	 * 목적지 IP·포트를 노드 id로 되돌린다.
	 *
	 * <p>포트를 함께 받는 것은 IP만으로 K8s API Server를 가리지 못하는 경우가 있어서다.
	 * 클러스터 밖 주소로 나가는 443/6443은 apiServerIp와 다르더라도 API Server 접근으로
	 * 본다 — 시나리오 1이 정확히 그 경로다.
	 */
	public String resolve(String dstIp, Integer dstPort) {
		if (dstIp == null) {
			return EXTERNAL_NODE;
		}
		String service = ipToService.get(dstIp);
		if (service != null) {
			return service;
		}
		if (dstIp.equals(apiServerIp) || isApiServerPort(dstPort)) {
			return K8S_API_NODE;
		}
		return EXTERNAL_NODE;
	}

	public NodeKind kindOf(String nodeId) {
		if (K8S_API_NODE.equals(nodeId)) {
			return NodeKind.K8S_API;
		}
		if (EXTERNAL_NODE.equals(nodeId)) {
			return NodeKind.EXTERNAL;
		}
		return serviceKinds.getOrDefault(nodeId, NodeKind.EXTERNAL);
	}

	private static boolean isApiServerPort(Integer port) {
		return port != null && (port == 443 || port == 6443);
	}
}
