package com.deepmesh.dashboard.stream;

import static org.assertj.core.api.Assertions.assertThat;

import com.deepmesh.dashboard.event.DetectionEvent;
import com.deepmesh.dashboard.event.PeerNaming;
import com.deepmesh.dashboard.topology.UnavailableClusterTopologySource;
import com.deepmesh.dashboard.stream.dto.StreamEvents;
import java.time.Clock;
import java.time.Instant;
import java.time.OffsetDateTime;
import java.time.ZoneOffset;
import java.util.ArrayList;
import java.util.List;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

/** 명세 2-2. 배치 상한과 알림 규칙. */
class DetectionBroadcasterTest {

	/** 무엇이 어떤 이름으로 나갔는지만 본다. 실제 전송은 SseHub의 몫이다. */
	private static class RecordingHub extends SseHub {
		final List<Object> detections = new ArrayList<>();
		final List<StreamEvents.Alert> alerts = new ArrayList<>();
		final List<String> ids = new ArrayList<>();
		int subscribers = 1;

		RecordingHub() {
			super(Clock.fixed(Instant.parse("2026-08-08T04:22:00Z"), ZoneOffset.ofHours(9)));
		}

		@Override
		public int subscriberCount() {
			return subscribers;
		}

		@Override
		public void broadcastWithId(String eventName, Object payload, String id) {
			detections.add(payload);
			ids.add(id);
		}

		@Override
		public void broadcast(String eventName, Object payload) {
			if (payload instanceof StreamEvents.Alert alert) {
				alerts.add(alert);
			}
		}
	}

	private RecordingHub hub;
	private DetectionBroadcaster broadcaster;

	@BeforeEach
	void setUp() {
		hub = new RecordingHub();
		broadcaster = new DetectionBroadcaster(hub, peerNaming());
	}

	/** K8s 없이 도는 대역. 이름은 안 붙지만 배치·알림 규칙 검증에는 무관하다. */
	private static PeerNaming peerNaming() {
		return new PeerNaming(new UnavailableClusterTopologySource());
	}

	private static DetectionEvent event(long id, String category, String verdict) {
		return DetectionEvent.builder()
				.eventId(id).serviceName("post-service").podName("post-service-a")
				.category(category).verdict(verdict)
				.occurredAt(OffsetDateTime.parse("2026-08-08T13:21:06+09:00"))
				.build();
	}

	private StreamEvents.DetectionBatch batch() {
		return (StreamEvents.DetectionBatch) hub.detections.get(0);
	}

	@Test
	void 쌓인_것이_없으면_아무것도_보내지_않는다() {
		broadcaster.flush();
		assertThat(hub.detections).isEmpty();
	}

	@Test
	void 구독자가_없으면_쌓지_않고_버린다() {
		hub.subscribers = 0;
		broadcaster.enqueue(List.of(event(1, "drop", "DROP")));
		broadcaster.flush();

		hub.subscribers = 1;
		broadcaster.flush();
		assertThat(hub.detections).isEmpty();   // 지난 것이 되살아나지 않는다
	}

	@Test
	void SSE_id는_배치의_최대_eventId다() {
		broadcaster.enqueue(List.of(event(7, "drop", "DROP"), event(19, "relay", "RELAY"),
				event(11, "cleared", "FORWARD")));
		broadcaster.flush();
		assertThat(hub.ids).containsExactly("19");
	}

	@Test
	void 배치는_eventId_오름차순이다() {
		broadcaster.enqueue(List.of(event(19, "drop", "DROP"), event(7, "drop", "DROP")));
		broadcaster.flush();
		assertThat(batch().events()).extracting("eventId").containsExactly("7", "19");
	}

	@Test
	void 상한을_넘으면_cleared부터_버린다() {
		List<DetectionEvent> events = new ArrayList<>();
		for (int i = 1; i <= DetectionBroadcaster.BATCH_LIMIT + 10; i++) {
			events.add(event(i, "cleared", "FORWARD"));
		}
		broadcaster.enqueue(events);
		broadcaster.flush();

		assertThat(batch().events()).hasSize(DetectionBroadcaster.BATCH_LIMIT);
		assertThat(batch().droppedCount()).isEqualTo(10);
	}

	@Test
	void drop과_relay는_상한을_넘겨도_버리지_않는다() {
		// 실제로 차단·대체가 일어난 사건이라 화면에서 빠지면 안 된다 (명세 2-2).
		List<DetectionEvent> events = new ArrayList<>();
		for (int i = 1; i <= DetectionBroadcaster.BATCH_LIMIT + 10; i++) {
			events.add(event(i, "drop", "DROP"));
		}
		broadcaster.enqueue(events);
		broadcaster.flush();

		assertThat(batch().events()).hasSize(DetectionBroadcaster.BATCH_LIMIT + 10);
		assertThat(batch().droppedCount()).isZero();
	}

	@Test
	void DROP은_HIGH_RELAY는_MEDIUM_알림이다() {
		broadcaster.enqueue(List.of(event(1, "drop", "DROP"), event(2, "relay", "RELAY")));
		broadcaster.flush();

		assertThat(hub.alerts).extracting(StreamEvents.Alert::severity)
				.containsExactly("HIGH", "MEDIUM");
		assertThat(hub.alerts).extracting(StreamEvents.Alert::eventId)
				.containsExactly("1", "2");
	}

	@Test
	void cleared는_알림을_내지_않는다() {
		// 서비스에 영향이 없었고 시스템이 의도대로 동작한 결과라 알림 피로만 유발한다.
		broadcaster.enqueue(List.of(event(1, "cleared", "FORWARD")));
		broadcaster.flush();

		assertThat(hub.alerts).isEmpty();
		assertThat(batch().events()).hasSize(1);   // 스트림과 이력에는 남는다
	}
}
