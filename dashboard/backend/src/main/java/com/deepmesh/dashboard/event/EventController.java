package com.deepmesh.dashboard.event;

import com.deepmesh.dashboard.event.EventQueryService.EventQuery;
import com.deepmesh.dashboard.event.dto.EventDetailResponse;
import com.deepmesh.dashboard.event.dto.EventPageResponse;
import java.time.OffsetDateTime;
import java.util.Arrays;
import java.util.List;
import lombok.RequiredArgsConstructor;
import org.springframework.format.annotation.DateTimeFormat;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

/** backend-frontend-api.md 1-7·1-8. 탐지 이벤트 조회. */
@RestController
@RequestMapping("/dashboard/events")
@RequiredArgsConstructor
public class EventController {

	private final EventQueryService service;

	@GetMapping
	public EventPageResponse list(
			@RequestParam(required = false) Long cursor,
			@RequestParam(required = false) Long afterId,
			@RequestParam(required = false) Integer size,
			@RequestParam(required = false) String verdict,
			@RequestParam(required = false) String serviceName,
			@RequestParam(required = false) String podName,
			@RequestParam(required = false) String direction,
			@RequestParam(required = false) @DateTimeFormat(iso = DateTimeFormat.ISO.DATE_TIME) OffsetDateTime from,
			@RequestParam(required = false) @DateTimeFormat(iso = DateTimeFormat.ISO.DATE_TIME) OffsetDateTime to) {
		List<String> verdicts = verdict == null ? null
				: Arrays.stream(verdict.split(",")).map(String::trim).filter(s -> !s.isEmpty()).toList();
		return service.list(new EventQuery(
				cursor, afterId, size, verdicts, serviceName, podName, direction, from, to));
	}

	@GetMapping("/{eventId}")
	public EventDetailResponse detail(@PathVariable long eventId) {
		return service.detail(eventId);
	}
}
