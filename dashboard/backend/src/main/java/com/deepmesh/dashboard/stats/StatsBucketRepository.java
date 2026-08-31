package com.deepmesh.dashboard.stats;

import java.time.OffsetDateTime;
import java.util.List;
import org.springframework.data.jpa.repository.JpaRepository;

public interface StatsBucketRepository extends JpaRepository<StatsBucket, Long> {

	/** 구간 내 집계 버킷. windowTo가 [from, to)에 드는 것을 본다. */
	List<StatsBucket> findByWindowToGreaterThanEqualAndWindowToLessThan(
			OffsetDateTime from, OffsetDateTime to);
}
