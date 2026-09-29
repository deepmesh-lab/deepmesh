package com.deepmesh.dashboard.config;

import java.time.Clock;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.scheduling.annotation.EnableScheduling;

@Configuration
// SSE의 stats(1s)·topology(1s)·detection(200ms) 주기 발행에 필요하다.
@EnableScheduling
public class AppConfig {

	/** 통계 구간의 '지금'을 계산하는 시계. 테스트에서 고정 시각으로 교체한다. */
	@Bean
	public Clock clock() {
		return Clock.systemDefaultZone();
	}
}
