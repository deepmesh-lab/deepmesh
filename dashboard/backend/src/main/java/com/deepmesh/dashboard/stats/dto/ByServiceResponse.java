package com.deepmesh.dashboard.stats.dto;

import java.time.OffsetDateTime;
import java.util.List;

/** backend-frontend-api.md 1-6 서비스별 판정 분포. */
public record ByServiceResponse(
		String timeRange,
		OffsetDateTime generatedAt,
		List<Row> rows
) {
	public record Row(
			String serviceName,
			long total,
			long benign,
			long cleared,
			long drop,
			long relay,
			double anomalyRate,
			double blockRate
	) {
	}
}
