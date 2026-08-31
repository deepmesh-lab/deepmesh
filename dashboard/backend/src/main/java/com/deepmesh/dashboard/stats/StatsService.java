package com.deepmesh.dashboard.stats;

import com.deepmesh.dashboard.common.ApiException;
import com.deepmesh.dashboard.common.ErrorCode;
import com.deepmesh.dashboard.common.TimeRange;
import com.deepmesh.dashboard.event.DetectionEvent;
import com.deepmesh.dashboard.event.DetectionEventRepository;
import com.deepmesh.dashboard.stats.dto.ByServiceResponse;
import com.deepmesh.dashboard.stats.dto.SummaryResponse;
import com.deepmesh.dashboard.stats.dto.TimeseriesResponse;
import java.time.Clock;
import java.time.Duration;
import java.time.OffsetDateTime;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import java.util.Map;
import java.util.TreeMap;
import java.util.stream.Collectors;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/**
 * backend-frontend-api.md 1-4·1-5·1-6. 집계 통계.
 *
 * <p>판정 분류 카운트는 StatsBucket(집계)에서, 지연 백분위수는 DetectionEvent에서 낸다.
 * 다만 지연은 개별 저장되는 attack 이벤트에만 있고 benign에는 없다(집계만 저장). 프록시가
 * Converter 결합 전이라 현재 detectionLatencyMs는 0이며, 결합 후 실제값으로 채워진다.
 */
@Service
@RequiredArgsConstructor
public class StatsService {

	private final StatsBucketRepository bucketRepository;
	private final DetectionEventRepository eventRepository;
	private final Clock clock;

	@Transactional(readOnly = true)
	public SummaryResponse summary(String timeRange) {
		TimeRange range = TimeRange.of(timeRange, now());
		List<StatsBucket> buckets = bucketsIn(range.from(), range.to(), null);

		long benign = buckets.stream().mapToLong(StatsBucket::getBenign).sum();
		long cleared = buckets.stream().mapToLong(StatsBucket::getCleared).sum();
		long drop = buckets.stream().mapToLong(StatsBucket::getDropCount).sum();
		long relay = buckets.stream().mapToLong(StatsBucket::getRelay).sum();
		long total = benign + cleared + drop + relay;

		List<Double> latencies = latenciesIn(range.from(), range.to(), null);

		return new SummaryResponse(
				range.label(), now(), total, benign, cleared, drop, relay,
				attackRate(total, cleared, drop, relay), blockRate(total, drop, relay),
				avg(latencies), percentile(latencies, 95),
				(int) buckets.stream().map(StatsBucket::getServiceName).distinct().count(),
				(int) buckets.stream().map(StatsBucket::getPodName).distinct().count());
	}

	@Transactional(readOnly = true)
	public ByServiceResponse byService(String timeRange) {
		TimeRange range = TimeRange.of(timeRange == null ? "1h" : timeRange, now());
		Map<String, List<StatsBucket>> byService = bucketsIn(range.from(), range.to(), null).stream()
				.collect(Collectors.groupingBy(StatsBucket::getServiceName));

		List<ByServiceResponse.Row> rows = new ArrayList<>();
		byService.forEach((service, list) -> {
			long benign = list.stream().mapToLong(StatsBucket::getBenign).sum();
			long cleared = list.stream().mapToLong(StatsBucket::getCleared).sum();
			long drop = list.stream().mapToLong(StatsBucket::getDropCount).sum();
			long relay = list.stream().mapToLong(StatsBucket::getRelay).sum();
			long total = benign + cleared + drop + relay;
			rows.add(new ByServiceResponse.Row(service, total, benign, cleared, drop, relay,
					attackRate(total, cleared, drop, relay), blockRate(total, drop, relay)));
		});
		// 문제가 있는 서비스가 맨 위로 — blockRate DESC, 동률이면 total DESC
		rows.sort(Comparator.comparingDouble(ByServiceResponse.Row::blockRate)
				.thenComparingLong(ByServiceResponse.Row::total).reversed());
		return new ByServiceResponse(range.label(), now(), rows);
	}

	@Transactional(readOnly = true)
	public TimeseriesResponse timeseries(OffsetDateTime from, OffsetDateTime to,
			String interval, String metric, String serviceName) {
		Duration step = parseInterval(interval);
		OffsetDateTime end = to != null ? to : now();
		OffsetDateTime start = from != null ? from : end.minusHours(1);
		if (!start.isBefore(end)) {
			throw new ApiException(ErrorCode.INVALID_TIME_RANGE, "from은 to보다 앞서야 합니다.");
		}
		// 버킷 경계로 정렬
		start = alignDown(start, step);
		end = alignDown(end.plus(step).minusNanos(1), step);
		if (Duration.between(start, end).dividedBy(step) > 1000) {
			throw new ApiException(ErrorCode.INVALID_TIME_RANGE, "버킷 수가 1000을 초과합니다.");
		}

		String m = metric == null ? "verdict" : metric;
		List<TimeseriesResponse.Bucket> buckets = switch (m) {
			case "verdict" -> verdictBuckets(start, end, step, serviceName);
			case "latency" -> latencyBuckets(start, end, step, serviceName);
			default -> throw new ApiException(ErrorCode.INVALID_PARAMETER, "알 수 없는 metric: " + m);
		};
		return new TimeseriesResponse(m, interval == null ? "1m" : interval, start, end,
				serviceName, buckets);
	}

	// --- verdict 시계열: 빈 구간도 0으로 채운다 ---
	private List<TimeseriesResponse.Bucket> verdictBuckets(OffsetDateTime start, OffsetDateTime end,
			Duration step, String serviceName) {
		// 버킷 키는 epoch 초로 잡는다. windowTo는 UTC로, 조회 범위는 KST로 올 수 있어
		// OffsetDateTime을 키로 쓰면 같은 순간도 offset이 달라 매핑이 빗나간다(모든 버킷 0).
		Map<Long, long[]> acc = new TreeMap<>();
		for (OffsetDateTime t = start; t.isBefore(end); t = t.plus(step)) {
			acc.put(t.toEpochSecond(), new long[4]);
		}
		for (StatsBucket b : bucketsIn(start, end, serviceName)) {
			long[] a = acc.get(alignDown(b.getWindowTo(), step).toEpochSecond());
			if (a != null) {
				a[0] += b.getBenign();
				a[1] += b.getCleared();
				a[2] += b.getDropCount();
				a[3] += b.getRelay();
			}
		}
		return acc.entrySet().stream()
				.map(e -> TimeseriesResponse.Bucket.verdict(
						atKst(e.getKey()), e.getValue()[0], e.getValue()[1], e.getValue()[2], e.getValue()[3]))
				.toList();
	}

	// --- latency 시계열: 데이터 없으면 null ---
	private List<TimeseriesResponse.Bucket> latencyBuckets(OffsetDateTime start, OffsetDateTime end,
			Duration step, String serviceName) {
		// verdictBuckets와 같은 이유로 epoch 초를 키로 쓴다 (offset 불일치 방지).
		Map<Long, List<Double>> acc = new TreeMap<>();
		for (OffsetDateTime t = start; t.isBefore(end); t = t.plus(step)) {
			acc.put(t.toEpochSecond(), new ArrayList<>());
		}
		for (DetectionEvent e : eventsIn(start, end, serviceName)) {
			if (e.getDetectionLatencyMs() == null) {
				continue;
			}
			List<Double> list = acc.get(alignDown(e.getOccurredAt(), step).toEpochSecond());
			if (list != null) {
				list.add(e.getDetectionLatencyMs());
			}
		}
		return acc.entrySet().stream()
				.map(e -> {
					List<Double> v = e.getValue();
					if (v.isEmpty()) {
						return TimeseriesResponse.Bucket.latency(atKst(e.getKey()), null, null, null, null);
					}
					return TimeseriesResponse.Bucket.latency(atKst(e.getKey()),
							percentile(v, 50), percentile(v, 95), percentile(v, 99), max(v));
				})
				.toList();
	}

	// --- 조회 헬퍼 ---
	private List<StatsBucket> bucketsIn(OffsetDateTime from, OffsetDateTime to, String serviceName) {
		List<StatsBucket> all = bucketRepository
				.findByWindowToGreaterThanEqualAndWindowToLessThan(from, to);
		return serviceName == null ? all
				: all.stream().filter(b -> serviceName.equals(b.getServiceName())).toList();
	}

	private List<Double> latenciesIn(OffsetDateTime from, OffsetDateTime to, String serviceName) {
		return eventsIn(from, to, serviceName).stream()
				.map(DetectionEvent::getDetectionLatencyMs)
				.filter(java.util.Objects::nonNull)
				.toList();
	}

	private List<DetectionEvent> eventsIn(OffsetDateTime from, OffsetDateTime to, String serviceName) {
		List<DetectionEvent> all = eventRepository
				.findByOccurredAtGreaterThanEqualAndOccurredAtLessThan(from, to);
		return serviceName == null ? all
				: all.stream().filter(e -> serviceName.equals(e.getServiceName())).toList();
	}

	// --- 계산 ---
	private OffsetDateTime now() {
		return OffsetDateTime.now(clock);
	}

	private double attackRate(long total, long cleared, long drop, long relay) {
		return total == 0 ? 0.0 : (double) (cleared + drop + relay) / total;
	}

	private double blockRate(long total, long drop, long relay) {
		return total == 0 ? 0.0 : (double) (drop + relay) / total;
	}

	private Double avg(List<Double> values) {
		if (values.isEmpty()) {
			return null;
		}
		return values.stream().mapToDouble(Double::doubleValue).average().orElse(0.0);
	}

	private Double max(List<Double> values) {
		return values.isEmpty() ? null
				: values.stream().mapToDouble(Double::doubleValue).max().getAsDouble();
	}

	/** nearest-rank 백분위수(p는 0~100). 데이터 없으면 null. */
	private Double percentile(List<Double> values, int p) {
		if (values.isEmpty()) {
			return null;
		}
		List<Double> sorted = values.stream().sorted().toList();
		int rank = (int) Math.ceil(p / 100.0 * sorted.size());
		return sorted.get(Math.max(0, Math.min(sorted.size() - 1, rank - 1)));
	}

	private Duration parseInterval(String interval) {
		return switch (interval == null ? "1m" : interval) {
			case "10s" -> Duration.ofSeconds(10);
			case "1m" -> Duration.ofMinutes(1);
			case "5m" -> Duration.ofMinutes(5);
			default -> throw new ApiException(ErrorCode.INVALID_PARAMETER, "알 수 없는 interval: " + interval);
		};
	}

	/** step 경계로 내림 정렬 (epoch 기준). */
	private OffsetDateTime alignDown(OffsetDateTime t, Duration step) {
		long stepSec = step.getSeconds();
		long epoch = t.toEpochSecond();
		long floored = epoch - Math.floorMod(epoch, stepSec);
		return OffsetDateTime.ofInstant(java.time.Instant.ofEpochSecond(floored), t.getOffset());
	}

	/** epoch 초를 KST 표기 OffsetDateTime으로. 화면은 KST로 시각을 읽는다(명세 1-1). */
	private static OffsetDateTime atKst(long epochSecond) {
		return OffsetDateTime.ofInstant(java.time.Instant.ofEpochSecond(epochSecond),
				java.time.ZoneOffset.ofHours(9));
	}
}
