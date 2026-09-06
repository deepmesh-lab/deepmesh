package com.deepmesh.dashboard.stats.dto;

import java.time.OffsetDateTime;

/** backend-frontend-api.md 1-4 상단 요약 카드. */
public record SummaryResponse(
		String timeRange,
		OffsetDateTime generatedAt,
		long totalSequences,
		long benignCount,
		long clearedCount,
		long dropCount,
		long relayCount,
		double anomalyRate,
		double blockRate,
		Double avgDetectionLatencyMs,
		Double p95DetectionLatencyMs,
		int activeServiceCount,
		int activePodCount
) {
}
