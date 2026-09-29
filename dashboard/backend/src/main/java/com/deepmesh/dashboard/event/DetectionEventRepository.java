package com.deepmesh.dashboard.event;

import java.time.OffsetDateTime;
import java.util.List;
import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.JpaSpecificationExecutor;

public interface DetectionEventRepository
		extends JpaRepository<DetectionEvent, Long>, JpaSpecificationExecutor<DetectionEvent> {

	/** 지연 통계용 — 구간 내 detectionLatencyMs 값만 뽑는다. */
	List<DetectionEvent> findByOccurredAtGreaterThanEqualAndOccurredAtLessThan(
			OffsetDateTime from, OffsetDateTime to);

	/** SSE 재전송 — Last-Event-ID 이후 이벤트 수 (명세 2-3). */
	long countByEventIdGreaterThan(long eventId);

	/** SSE 재전송 — Last-Event-ID 이후 이벤트. 정렬·개수는 호출부가 정한다. */
	List<DetectionEvent> findByEventIdGreaterThan(long eventId, Pageable pageable);
}
