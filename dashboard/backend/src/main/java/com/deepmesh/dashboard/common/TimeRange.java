package com.deepmesh.dashboard.common;

import java.time.Duration;
import java.time.OffsetDateTime;

/**
 * timeRange 문자열(1m/5m/15m/30m/1h/6h/24h)을 [from, now) 구간으로 해석한다.
 *
 * <p>지금(now)을 인자로 받는다 — 테스트에서 고정 시각을 넣기 위함이다.
 */
public record TimeRange(OffsetDateTime from, OffsetDateTime to, String label) {

	public static TimeRange of(String label, OffsetDateTime now) {
		Duration d = switch (label == null ? "5m" : label) {
			case "1m" -> Duration.ofMinutes(1);
			case "5m" -> Duration.ofMinutes(5);
			case "15m" -> Duration.ofMinutes(15);
			case "30m" -> Duration.ofMinutes(30);
			case "1h" -> Duration.ofHours(1);
			case "6h" -> Duration.ofHours(6);
			case "24h" -> Duration.ofHours(24);
			default -> throw new ApiException(ErrorCode.INVALID_PARAMETER,
					"알 수 없는 timeRange: " + label);
		};
		return new TimeRange(now.minus(d), now, label == null ? "5m" : label);
	}
}
