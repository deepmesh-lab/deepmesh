package com.deepmesh.dashboard.event;

import java.time.OffsetDateTime;
import java.util.List;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.JpaSpecificationExecutor;

public interface DetectionEventRepository
		extends JpaRepository<DetectionEvent, Long>, JpaSpecificationExecutor<DetectionEvent> {

	/** 지연 통계용 — 구간 내 detectionLatencyMs 값만 뽑는다. */
	List<DetectionEvent> findByOccurredAtGreaterThanEqualAndOccurredAtLessThan(
			OffsetDateTime from, OffsetDateTime to);
}
