package com.deepmesh.dashboard.stream;

import com.deepmesh.dashboard.stats.StatsService;
import com.deepmesh.dashboard.stats.dto.SummaryResponse;
import com.deepmesh.dashboard.stream.dto.StreamEvents;
import lombok.RequiredArgsConstructor;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

/**
 * 1초 고정 주기 통계 틱 (명세 2-2).
 *
 * <p>이벤트가 0건이어도 보낸다. 프론트가 이걸 연결 생존 신호로도 쓰기 때문에, 조용하다고
 * 건너뛰면 살아 있는 연결이 죽은 것처럼 보인다.
 */
@Component
@RequiredArgsConstructor
public class StatsBroadcaster {

	/** 이동 집계 구간. 이 틱은 "최근 1분간의 집계"라는 뜻이다. */
	static final String TICK_RANGE = "1m";

	private final StatsService statsService;
	private final SseHub hub;

	@Scheduled(fixedRate = 1000)
	public void tick() {
		if (hub.subscriberCount() == 0) {
			return;
		}
		SummaryResponse summary = statsService.summary(TICK_RANGE);
		// p95는 담지 않는다 — 1초 표본으로 백분위수를 내면 값이 심하게 흔들린다.
		hub.broadcast("stats", new StreamEvents.StatsTick(
				"STATS_TICK", summary.generatedAt(), TICK_RANGE,
				summary.totalSequences(), summary.benignCount(), summary.clearedCount(),
				summary.dropCount(), summary.relayCount(),
				summary.anomalyRate(), summary.blockRate(), summary.avgDetectionLatencyMs()));
	}

	@Scheduled(fixedRate = 5000)
	public void heartbeat() {
		hub.heartbeat();
	}
}
