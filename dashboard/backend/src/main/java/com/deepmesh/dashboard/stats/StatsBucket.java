package com.deepmesh.dashboard.stats;

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
	 * 판정이 drop인 시퀀스 수.
	 *
	 * <p>필드명을 drop으로 두지 않는다. 그러면 컬럼이 MySQL 예약어가 되어 create table이
	 * 문법 오류로 실패한다. @Column으로 따옴표를 씌우는 방법은 Spring Boot의 네이밍
	 * 전략을 거치며 인용이 벗겨져 통하지 않았다. 이름을 바꾸는 쪽이 확실하다.
	 *
	 * <p>H2는 drop을 컬럼 이름으로 허용해서 테스트로는 드러나지 않는다.
	 */
	private long dropCount;
	private long relay;
}
