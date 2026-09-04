package com.deepmesh.dashboard.stream;

import com.deepmesh.dashboard.event.DetectionEvent;
import com.deepmesh.dashboard.event.DetectionEventRepository;
import com.deepmesh.dashboard.event.PeerNaming;
import com.deepmesh.dashboard.event.dto.EventResponse;
import com.deepmesh.dashboard.stream.dto.StreamEvents;
import com.deepmesh.dashboard.topology.dto.TopologyResponse;
import java.util.List;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.data.domain.PageRequest;
import org.springframework.data.domain.Sort;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

/**
 * backend-frontend-api.md 2장. 실시간 이벤트 스트림.
 *
 * <p>연결 순서는 명세 2-3의 재전송 흐름을 따른다.
 * <ol>
 *   <li>Last-Event-ID가 있으면 그 이후 detection 이벤트를 먼저 재전송
 *   <li>토폴로지 전체 스냅샷 1회
 *   <li>라이브 스트림 등록(이 시점부터 브로드캐스트가 닿는다)
 * </ol>
 */
@RestController
@Slf4j
@RequiredArgsConstructor
public class StreamController {

	/** 한 번에 재전송할 상한. 넘으면 최근 것만 보내고 gap 이벤트로 알린다 (명세 2-3). */
	static final int REPLAY_LIMIT = 500;

	/** 상한을 넘었을 때 실제로 보내는 수. */
	static final int REPLAY_TRUNCATED_TO = 200;

	private final SseHub hub;
	private final DetectionEventRepository eventRepository;
	private final TopologyBroadcaster topology;
	private final PeerNaming peerNaming;

	@GetMapping(value = "/dashboard/stream", produces = MediaType.TEXT_EVENT_STREAM_VALUE)
	public ResponseEntity<SseEmitter> stream(
			@RequestHeader(value = "Last-Event-ID", required = false) String lastEventId,
			/*
			 * 화면이 보고 있는 집계 구간. 스냅샷·델타를 이 구간으로 만든다.
			 *
			 * 받지 않고 5m으로 고정했더니, 1시간을 보는 화면에 "최근 5분에는 간선이 없다"는
			 * 빈 스냅샷이 덮여 그래프가 통째로 비었다. 스냅샷은 병합이 아니라 교체다.
			 */
			@RequestParam(defaultValue = "5m") String timeRange) {

		SseEmitter emitter = hub.subscribe(timeRange);
		replay(emitter, lastEventId);

		TopologyResponse snapshot = topology.snapshot(timeRange);
		if (snapshot != null) {
			// 최초 연결과 재연결 모두에서 보낸다. 토폴로지는 델타를 소급 적용할 수 없어
			// 단절 구간 이후의 누적 상태를 신뢰할 수 없다.
			hub.sendTo(emitter, "topology", StreamEvents.TopologySnapshot.of(
					hub.now(), snapshot.nodes(), snapshot.edges()), null);
		}

		return ResponseEntity.ok()
				.header("Cache-Control", "no-cache")
				.header("Connection", "keep-alive")
				// 없으면 Nginx가 응답을 모아 내보내 이벤트가 실시간으로 도착하지 않는다.
				.header("X-Accel-Buffering", "no")
				.body(emitter);
	}

	/** Last-Event-ID 이후의 detection 이벤트를 시간순으로 다시 보낸다. */
	private void replay(SseEmitter emitter, String lastEventId) {
		Long cursor = parseCursor(lastEventId);
		if (cursor == null) {
			return;
		}
		long missed = eventRepository.countByEventIdGreaterThan(cursor);
		if (missed == 0) {
			return;
		}
		boolean truncated = missed > REPLAY_LIMIT;
		int size = truncated ? REPLAY_TRUNCATED_TO : (int) missed;

		// 잘릴 때는 '최근' 것을 보내야 하므로 내림차순으로 뽑고 되돌린다.
		List<DetectionEvent> events = new java.util.ArrayList<>(
				eventRepository.findByEventIdGreaterThan(cursor,
						PageRequest.of(0, size, Sort.by(
								truncated ? Sort.Direction.DESC : Sort.Direction.ASC, "eventId"))));
		if (truncated) {
			java.util.Collections.reverse(events);
			hub.sendTo(emitter, "gap", StreamEvents.ReplayTruncated.of(
					(int) missed - events.size(), events.get(0).getOccurredAt()), null);
		}
		List<EventResponse> items = peerNaming.name(events);
		hub.sendTo(emitter, "detection",
				StreamEvents.DetectionBatch.of(hub.now(), items, 0),
				String.valueOf(events.get(events.size() - 1).getEventId()));
	}

	private static Long parseCursor(String lastEventId) {
		if (lastEventId == null || lastEventId.isBlank()) {
			return null;
		}
		try {
			return Long.parseLong(lastEventId.trim());
		} catch (NumberFormatException exc) {
			// 브라우저가 보낸 값이 망가졌다. 재전송 없이 라이브만 붙인다 — 400으로
			// 끊으면 EventSource가 재연결을 포기(readyState=2)해 복구가 막힌다.
			log.debug("Last-Event-ID 해석 실패, 재전송 생략: {}", lastEventId);
			return null;
		}
	}
}
