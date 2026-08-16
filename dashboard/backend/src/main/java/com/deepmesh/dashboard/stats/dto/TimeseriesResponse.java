package com.deepmesh.dashboard.stats.dto;

import com.fasterxml.jackson.annotation.JsonInclude;
import java.time.OffsetDateTime;
import java.util.List;

/**
 * backend-frontend-api.md 1-5 시계열. metric에 따라 버킷 스키마가 달라진다.
 *
 * <p>verdict 버킷은 빈 구간도 0으로 채운다. latency 버킷은 데이터가 없으면 null이다
 * (0은 물리적으로 불가능한 값이라 차트를 오도한다).
 */
public record TimeseriesResponse(
		String metric,
		String interval,
		OffsetDateTime from,
		OffsetDateTime to,
		String serviceName,
		List<Bucket> buckets
) {
	@JsonInclude(JsonInclude.Include.NON_NULL)
	public record Bucket(
			OffsetDateTime ts,
			// verdict
			Long benign,
			Long cleared,
			Long drop,
			Long relay,
			// latency
			Double p50,
			Double p95,
			Double p99,
			Double max
	) {
		public static Bucket verdict(OffsetDateTime ts, long benign, long cleared, long drop, long relay) {
			return new Bucket(ts, benign, cleared, drop, relay, null, null, null, null);
		}

		public static Bucket latency(OffsetDateTime ts, Double p50, Double p95, Double p99, Double max) {
			return new Bucket(ts, null, null, null, null, p50, p95, p99, max);
		}
	}
}
