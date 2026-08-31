package com.deepmesh.dashboard.support;

import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Primary;

/** 통계 구간의 '지금'을 테스트 데이터 시각 근처로 고정한다. */
@TestConfiguration
public class FixedClockConfig {

	/** 2026-08-08T13:22:00+09:00 근처로 고정 — 테스트 데이터가 5m/1h 구간에 들도록. */
	public static final Instant NOW = Instant.parse("2026-08-08T04:22:00Z");

	@Bean
	@Primary
	public Clock testClock() {
		return Clock.fixed(NOW, ZoneOffset.ofHours(9));
	}
}
