package com.deepmesh.dashboard.event;

import com.deepmesh.dashboard.event.EventQueryService.EventQuery;
import com.deepmesh.dashboard.event.dto.EventDetailResponse;
import com.deepmesh.dashboard.event.dto.EventPageResponse;
import jakarta.servlet.http.HttpServletResponse;
import java.io.IOException;
import java.time.OffsetDateTime;
import java.time.ZoneOffset;
import java.time.format.DateTimeFormatter;
import java.util.Arrays;
import java.util.List;
import lombok.RequiredArgsConstructor;
import org.springframework.format.annotation.DateTimeFormat;
import org.springframework.http.HttpHeaders;
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
			@RequestParam(required = false) String category,
			@RequestParam(required = false) String serviceName,
			@RequestParam(required = false) String podName,
			@RequestParam(required = false) String direction,
			@RequestParam(required = false) @DateTimeFormat(iso = DateTimeFormat.ISO.DATE_TIME) OffsetDateTime from,
			@RequestParam(required = false) @DateTimeFormat(iso = DateTimeFormat.ISO.DATE_TIME) OffsetDateTime to) {
		return service.list(new EventQuery(cursor, afterId, size, parseVerdicts(verdict),
				parseVerdicts(category), serviceName, podName, direction, from, to));
	}

	/** 콤마 구분 다중 지정. verdict·category와 목록·내려받기가 모두 같은 규칙을 쓴다. */
	private static List<String> parseVerdicts(String verdict) {
		return verdict == null ? null
				: Arrays.stream(verdict.split(",")).map(String::trim).filter(s -> !s.isEmpty()).toList();
	}

	@GetMapping("/{eventId}")
	public EventDetailResponse detail(@PathVariable long eventId) {
		return service.detail(eventId);
	}

	/**
	 * 필터에 해당하는 전체를 CSV로 내려받는다. 페이지네이션이 없으므로 cursor·afterId·size는
	 * 받지 않는다.
	 *
	 * <p>StreamingResponseBody를 쓰지 않고 응답에 직접 쓴다. 비동기 디스패치가 끼면
	 * 테스트가 복잡해지는 데 비해, 백엔드 replicas가 1이고 내려받기가 간헐적인 이 환경에서
	 * 서블릿 스레드를 잡는 비용은 문제가 되지 않는다.
	 *
	 * <p>스트리밍이 시작된 뒤 조회가 실패하면 이미 200과 헤더를 보낸 뒤라 상태 코드로 알릴 수
	 * 없다. 그때는 예외를 그대로 올려 응답을 끝맺지 않는다 — 브라우저가 다운로드를 실패로
	 * 표시하므로 잘린 파일을 완전한 것으로 오인하지 않는다.
	 */
	@GetMapping("/export")
	public void export(
			@RequestParam(required = false) String verdict,
			@RequestParam(required = false) String category,
			@RequestParam(required = false) String serviceName,
			@RequestParam(required = false) String podName,
			@RequestParam(required = false) String direction,
			@RequestParam(required = false) @DateTimeFormat(iso = DateTimeFormat.ISO.DATE_TIME) OffsetDateTime from,
			@RequestParam(required = false) @DateTimeFormat(iso = DateTimeFormat.ISO.DATE_TIME) OffsetDateTime to,
			HttpServletResponse response) throws IOException {
		// getWriter()보다 먼저 불러야 UTF-8로 인코딩된다.
		response.setContentType("text/csv; charset=UTF-8");
		response.setHeader(HttpHeaders.CONTENT_DISPOSITION,
				"attachment; filename=\"" + exportFilename() + "\"");

		service.exportCsv(new EventQuery(null, null, null, parseVerdicts(verdict),
				parseVerdicts(category), serviceName, podName, direction, from, to),
				response.getWriter());
	}

	private static String exportFilename() {
		return "deepmesh-events_"
				+ OffsetDateTime.now(ZoneOffset.ofHours(9))
						.format(DateTimeFormatter.ofPattern("yyyyMMdd-HHmm"))
				+ ".csv";
	}
}
