package com.deepmesh.dashboard.stats;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Index;
import jakarta.persistence.Table;
import java.time.OffsetDateTime;
import lombok.AccessLevel;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Getter;
import lombok.NoArgsConstructor;

/**
 * 프록시가 1초 주기로 보내는 windowStats 집계 한 건.
 *
 * <p>benign을 포함한 4분류 카운트를 담는다. /dashboard/stats/* 시계열의 원천이다.
 * 개별 이벤트(detection_event)와 달리 benign도 여기서 집계된다.
 */
@Entity
@Table(name = "stats_bucket", indexes = {
		@Index(name = "idx_stats_service_to", columnList = "serviceName, windowTo")
})
@Getter
@NoArgsConstructor(access = AccessLevel.PROTECTED)
@AllArgsConstructor(access = AccessLevel.PRIVATE)
@Builder
public class StatsBucket {

	@Id
	@GeneratedValue(strategy = GenerationType.IDENTITY)
	private Long id;

	private String serviceName;
	private String podName;

	private OffsetDateTime windowFrom;
	private OffsetDateTime windowTo;

	private long benign;
	private long cleared;
	/**
	 * MySQL 예약어라 컬럼 이름을 따옴표로 감싼다. H2는 그냥 통과시켜서 테스트에서는
	 * 드러나지 않고, MySQL에서만 create table이 문법 오류로 실패한다.
	 */
	@Column(name = "`drop`")
	private long drop;
	private long relay;
}
