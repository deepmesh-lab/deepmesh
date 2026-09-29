package com.deepmesh.dashboard.topology.dto;

import com.deepmesh.dashboard.topology.NodeStatus;
import java.time.OffsetDateTime;
import java.util.List;

/** backend-frontend-api.md 1-3. 토폴로지 노드 클릭 시 replica 상세 패널. */
public record ServiceDetailResponse(
		String serviceName,
		String namespace,
		String replicaSetName,
		String timeRange,
		OffsetDateTime generatedAt,
		List<PodResponse> pods) {

	/**
	 * Pod 한 줄. 시나리오 2 시연에서 침해된 Pod와 정상 replica의 판정 분포 차이가
	 * 여기서 드러난다.
	 */
	public record PodResponse(
			String podName,
			String podIp,
			String nodeName,
			String phase,
			boolean ready,
			OffsetDateTime startedAt,
			boolean proxyReady,
			/** 이 프록시에 탑재된 모델. replica 간 값이 다르면 배포가 어긋난 것이다. */
			String modelId,
			CountsResponse counts,
			NodeStatus status) {
	}
}
