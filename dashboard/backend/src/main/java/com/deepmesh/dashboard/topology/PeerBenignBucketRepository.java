package com.deepmesh.dashboard.topology;

import java.time.OffsetDateTime;
import java.util.List;
import org.springframework.data.jpa.repository.JpaRepository;

public interface PeerBenignBucketRepository extends JpaRepository<PeerBenignBucket, Long> {

	/** 구간 내 목적지별 benign 집계. windowTo가 [from, to)에 드는 것을 본다. */
	List<PeerBenignBucket> findByWindowToGreaterThanEqualAndWindowToLessThan(
			OffsetDateTime from, OffsetDateTime to);
}
