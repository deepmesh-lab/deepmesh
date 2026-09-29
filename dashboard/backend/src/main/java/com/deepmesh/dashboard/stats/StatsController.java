package com.deepmesh.dashboard.stats;

import com.deepmesh.dashboard.stats.dto.ByServiceResponse;
import com.deepmesh.dashboard.stats.dto.SummaryResponse;
import com.deepmesh.dashboard.stats.dto.TimeseriesResponse;
import java.time.OffsetDateTime;
import lombok.RequiredArgsConstructor;
import org.springframework.format.annotation.DateTimeFormat;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

/** backend-frontend-api.md 1-4·1-5·1-6. 집계 통계 조회. */
@RestController
@RequestMapping("/dashboard/stats")
@RequiredArgsConstructor
public class StatsController {

	private final StatsService service;

	@GetMapping("/summary")
	public SummaryResponse summary(@RequestParam(required = false, defaultValue = "5m") String timeRange) {
		return service.summary(timeRange);
	}

	@GetMapping("/by-service")
	public ByServiceResponse byService(@RequestParam(required = false, defaultValue = "1h") String timeRange) {
		return service.byService(timeRange);
	}

	@GetMapping("/timeseries")
	public TimeseriesResponse timeseries(
			@RequestParam(required = false) @DateTimeFormat(iso = DateTimeFormat.ISO.DATE_TIME) OffsetDateTime from,
			@RequestParam(required = false) @DateTimeFormat(iso = DateTimeFormat.ISO.DATE_TIME) OffsetDateTime to,
			@RequestParam(required = false, defaultValue = "1m") String interval,
			@RequestParam(required = false, defaultValue = "verdict") String metric,
			@RequestParam(required = false) String serviceName) {
		return service.timeseries(from, to, interval, metric, serviceName);
	}
}
