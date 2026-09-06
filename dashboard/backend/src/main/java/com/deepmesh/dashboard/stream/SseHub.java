package com.deepmesh.dashboard.stream;

import java.io.IOException;
import java.time.Clock;
import java.time.Duration;
import java.time.OffsetDateTime;
import java.util.List;
import java.util.concurrent.CopyOnWriteArrayList;
import java.util.concurrent.atomic.AtomicReference;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Component;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

/**
 * 열려 있는 SSE 연결을 들고 브로드캐스트한다.
 *
 * <p>구독자별 필터링은 하지 않는다 — 스트림은 전 종류를 흘리고 필터링은 프론트가 한다
 * (명세 2-1). 동시 접속이 관리자 소수라 서버 사이드 필터링의 이득보다 복잡도가 크다.
 *
 * <p>전송 실패는 구독 해제로 처리한다. 끊긴 연결에 계속 쓰면 예외가 매 틱마다 쌓이고,
 * 브라우저는 어차피 스스로 재연결한다.
 */
@Component
@Slf4j
@RequiredArgsConstructor
public class SseHub {

	/**
	 * 무한(0L)이 아니라 1시간으로 둔다 (명세 2-4). 만료되면 정상 종료되고 브라우저가
	 * 재연결하므로, 영원히 살아 있는 연결이 쌓이는 것을 막는다.
	 */
	static final long TIMEOUT_MILLIS = Duration.ofHours(1).toMillis();

	/** 이 시간 동안 아무 이벤트도 없으면 주석 줄을 보낸다. 중간 프록시의 유휴 타임아웃 방지. */
	static final Duration HEARTBEAT_AFTER = Duration.ofSeconds(15);

	/** 재연결 대기(ms). 연결 직후 1회만 보낸다. */
	static final long RETRY_MILLIS = 3000;

	private final List<Subscriber> subscribers = new CopyOnWriteArrayList<>();
	private final Clock clock;

	/**
	 * 구독자를 등록한다.
	 *
	 * <p>{@code timeRange}를 함께 들고 있는 이유 — 토폴로지 델타는 집계 구간에 따라 값이
	 * 다르다. 구간을 무시하고 하나로 방송하면 1시간을 보고 있는 화면에 5분치 계산 결과가
	 * 덮여 간선이 통째로 사라진다.
	 */
	public SseEmitter subscribe(String timeRange) {
		SseEmitter emitter = new SseEmitter(TIMEOUT_MILLIS);
		Subscriber subscriber =
				new Subscriber(emitter, clock.instant().toEpochMilli(), timeRange);
		subscribers.add(subscriber);
		emitter.onCompletion(() -> subscribers.remove(subscriber));
		emitter.onTimeout(() -> subscribers.remove(subscriber));
		emitter.onError(e -> subscribers.remove(subscriber));
		try {
			emitter.send(SseEmitter.event().reconnectTime(RETRY_MILLIS).comment("connected"));
		} catch (IOException exc) {
			subscribers.remove(subscriber);
		}
		return emitter;
	}

	public int subscriberCount() {
		return subscribers.size();
	}

	/** 지금 붙어 있는 구독자들이 보고 있는 집계 구간. 델타를 구간별로 만들기 위해 쓴다. */
	public java.util.Set<String> activeTimeRanges() {
		java.util.Set<String> ranges = new java.util.LinkedHashSet<>();
		for (Subscriber subscriber : subscribers) {
			ranges.add(subscriber.timeRange);
		}
		return ranges;
	}

	/** 같은 집계 구간을 보고 있는 구독자에게만 보낸다. */
	public void broadcastTo(String timeRange, String eventName, Object payload) {
		for (Subscriber subscriber : subscribers) {
			if (subscriber.timeRange.equals(timeRange)) {
				deliver(subscriber, eventName, payload, null);
			}
		}
	}

	/**
	 * id 없는 이벤트를 보낸다.
	 *
	 * <p>id는 detection에만 붙인다 (명세 2-3). SSE의 Last-Event-ID는 스트림 전체에 하나뿐인
	 * 값이라, stats에도 id를 주면 재연결 직전에 흐른 것이 stats일 때 그 값으로 덮어써져
	 * 어느 detection이 유실됐는지 판단할 수 없게 된다.
	 */
	public void broadcast(String eventName, Object payload) {
		send(eventName, payload, null);
	}

	/** detection 전용 — id는 그 배치의 최대 eventId다. */
	public void broadcastWithId(String eventName, Object payload, String id) {
		send(eventName, payload, id);
	}

	/** 한 구독자에게만 보낸다. 연결 직후 스냅샷·재전송에 쓴다. */
	public void sendTo(SseEmitter emitter, String eventName, Object payload, String id) {
		Subscriber target = find(emitter);
		if (target != null) {
			deliver(target, eventName, payload, id);
		}
	}

	/** 조용한 연결에 주석 줄을 흘린다. EventSource가 무시하는 줄이라 프론트에 영향이 없다. */
	public void heartbeat() {
		long deadline = clock.instant().minus(HEARTBEAT_AFTER).toEpochMilli();
		for (Subscriber subscriber : subscribers) {
			if (subscriber.lastSentAt < deadline) {
				try {
					subscriber.emitter.send(SseEmitter.event().comment("keep-alive"));
					subscriber.lastSentAt = clock.instant().toEpochMilli();
				} catch (Exception exc) {
					drop(subscriber);
				}
			}
		}
	}

	private void send(String eventName, Object payload, String id) {
		for (Subscriber subscriber : subscribers) {
			deliver(subscriber, eventName, payload, id);
		}
	}

	private void deliver(Subscriber subscriber, String eventName, Object payload, String id) {
		try {
			SseEmitter.SseEventBuilder event = SseEmitter.event().name(eventName).data(payload);
			if (id != null) {
				event = event.id(id);
			}
			subscriber.emitter.send(event);
			subscriber.lastSentAt = clock.instant().toEpochMilli();
		} catch (Exception exc) {
			drop(subscriber);
		}
	}

	private void drop(Subscriber subscriber) {
		subscribers.remove(subscriber);
		try {
			subscriber.emitter.complete();
		} catch (Exception ignored) {
			// 이미 끊긴 연결이다. 브라우저가 재연결한다.
		}
	}

	private Subscriber find(SseEmitter emitter) {
		return subscribers.stream().filter(s -> s.emitter == emitter).findFirst().orElse(null);
	}

	OffsetDateTime now() {
		return OffsetDateTime.now(clock);
	}

	private static final class Subscriber {
		private final SseEmitter emitter;
		private volatile long lastSentAt;
		/** 이 구독자가 보고 있는 집계 구간. 토폴로지 델타를 이 값으로 갈라 보낸다. */
		private final String timeRange;

		private Subscriber(SseEmitter emitter, long lastSentAt, String timeRange) {
			this.emitter = emitter;
			this.lastSentAt = lastSentAt;
			this.timeRange = timeRange;
		}
	}
}
