package com.deepmesh.dashboard.stream;

import com.deepmesh.dashboard.event.DetectionEvent;
import com.deepmesh.dashboard.event.PeerNaming;
import com.deepmesh.dashboard.event.dto.EventResponse;
import com.deepmesh.dashboard.stream.dto.StreamEvents;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import java.util.concurrent.ConcurrentLinkedQueue;
import lombok.RequiredArgsConstructor;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

/**
 * 수집된 ATTACK 이벤트를 200ms 배치로 흘리고, DROP·RELAY에는 알림을 함께 발행한다
 * (명세 2-2).
 *
 * <p>배치로 묶는 이유는 짧은 시간에 판정이 몰리는 경우(브루트포스 계열)를 대비하기
 * 위함이다. 평시에는 이벤트가 드물어 배치당 1건 이하다.
 */
@Component
@RequiredArgsConstructor
public class DetectionBroadcaster {

	/** 배치당 상한. 넘치면 benign → cleared 순으로 버린다. */
	static final int BATCH_LIMIT = 100;

	/**
	 * 상한을 넘겼을 때 버리는 순서. 앞의 것부터 버린다.
	 *
	 * <p>benign이 가장 먼저다 — 판정이 정상이었고 집계로도 남아 있어, 실시간 화면에서
	 * 빠져도 잃는 것이 가장 적다. drop·relay는 이 목록에 없어 절대 버려지지 않는다.
	 */
	private static final List<String> DISCARD_ORDER = List.of("benign", "cleared");

	private final ConcurrentLinkedQueue<DetectionEvent> pending = new ConcurrentLinkedQueue<>();
	private final SseHub hub;
	/** 목적지 이름을 REST 목록과 같은 규칙으로 붙인다. */
	private final PeerNaming peerNaming;

	/** 수집 직후 호출된다. 저장이 끝난 이벤트만 들어와야 재전송 커서와 어긋나지 않는다. */
	public void enqueue(List<DetectionEvent> events) {
		pending.addAll(events);
	}

	@Scheduled(fixedRate = 200)
	public void flush() {
		if (pending.isEmpty() || hub.subscriberCount() == 0) {
			pending.clear();   // 구독자가 없으면 쌓아둘 이유가 없다
			return;
		}
		List<DetectionEvent> batch = new ArrayList<>();
		DetectionEvent event;
		while ((event = pending.poll()) != null) {
			batch.add(event);
		}

		int dropped = trim(batch);
		batch.sort(Comparator.comparing(DetectionEvent::getEventId));

		List<EventResponse> items = peerNaming.name(batch);
		String maxEventId = String.valueOf(batch.get(batch.size() - 1).getEventId());
		hub.broadcastWithId("detection",
				StreamEvents.DetectionBatch.of(hub.now(), items, dropped), maxEventId);

		for (DetectionEvent e : batch) {
			alertFor(e).ifPresent(alert -> hub.broadcast("alert", alert));
		}
	}

	/**
	 * 상한을 넘치면 DISCARD_ORDER 순으로 버린다. drop·relay는 절대 버리지 않는다
	 * (명세 2-2) — 실제로 차단·대체가 일어난 사건이라 화면에서 빠지면 안 된다. 그래서
	 * drop·relay가 상한보다 많으면 배치가 상한을 넘어서 나간다.
	 *
	 * @return 버린 수
	 */
	private static int trim(List<DetectionEvent> batch) {
		int excess = batch.size() - BATCH_LIMIT;
		if (excess <= 0) {
			return 0;
		}
		int dropped = 0;
		for (String category : DISCARD_ORDER) {
			for (int i = batch.size() - 1; i >= 0 && dropped < excess; i--) {
				if (category.equals(batch.get(i).getCategory())) {
					batch.remove(i);
					dropped++;
				}
			}
			if (dropped >= excess) {
				break;
			}
		}
		return dropped;
	}

	/** cleared는 알림을 내지 않는다 — 서비스에 영향이 없었고 알림 피로만 유발한다. */
	private static java.util.Optional<StreamEvents.Alert> alertFor(DetectionEvent e) {
		String severity = switch (e.getVerdict() == null ? "" : e.getVerdict()) {
			case "DROP" -> "HIGH";     // 요청이 실제로 차단됨
			case "RELAY" -> "MEDIUM";  // 정상 응답으로 대체되어 가용성은 유지됨
			default -> null;
		};
		if (severity == null) {
			return java.util.Optional.empty();
		}
		String title = "DROP".equals(e.getVerdict())
				? "비인가 요청 차단" : "변조 응답 대체";
		String message = "%s 에서 %s".formatted(e.getPodName(),
				"DROP".equals(e.getVerdict())
						? "관측되지 않은 요청이 발생하여 차단되었습니다."
						: "응답 불일치가 확인되어 정상 replica의 응답으로 대체되었습니다.");
		return java.util.Optional.of(new StreamEvents.Alert("ALERT", severity,
				String.valueOf(e.getEventId()), e.getOccurredAt(), e.getVerdict(),
				e.getServiceName(), e.getPodName(), title, message));
	}
}
