package com.deepmesh.dashboard.topology.dto;

import java.time.OffsetDateTime;
import java.util.List;

/** backend-frontend-api.md 1-2. React Flow 초기 렌더용 토폴로지 스냅샷. */
public record TopologyResponse(
		OffsetDateTime generatedAt,
		String timeRange,
		String namespace,
		List<NodeResponse> nodes,
		List<EdgeResponse> edges) {
}
