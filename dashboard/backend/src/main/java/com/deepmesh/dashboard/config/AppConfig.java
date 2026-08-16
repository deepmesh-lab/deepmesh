package com.deepmesh.dashboard.config;

import java.time.Clock;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration
public class AppConfig {

	/** 통계 구간의 '지금'을 계산하는 시계. 테스트에서 고정 시각으로 교체한다. */
	@Bean
	public Clock clock() {
		return Clock.systemDefaultZone();
	}
}
