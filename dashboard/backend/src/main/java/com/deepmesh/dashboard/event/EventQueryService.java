package com.deepmesh.dashboard.event;

import com.deepmesh.dashboard.common.ApiException;
import com.deepmesh.dashboard.common.ErrorCode;
import com.deepmesh.dashboard.event.dto.EventDetailResponse;
import com.deepmesh.dashboard.event.dto.EventPageResponse;
import com.deepmesh.dashboard.event.dto.EventResponse;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import jakarta.persistence.criteria.Predicate;
import java.time.OffsetDateTime;
import java.util.ArrayList;
import java.util.List;
import lombok.RequiredArgsConstructor;
import org.springframework.data.domain.PageRequest;
import org.springframework.data.domain.Sort;
import org.springframework.data.jpa.domain.Specification;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/**
 * backend-frontend-api.md 1-7·1-8. 커서 페이지네이션과 필터로 이벤트를 조회한다.
 *
 * <p>eventId가 시간 단조 증가하므로 이를 커서로 삼는다. cursor는 미만(과거)으로 내림차순,
 * afterId는 초과(신규)로 오름차순(재연결 갭 필링). 둘은 상호 배타다.
 */
@Service
@RequiredArgsConstructor
public class EventQueryService {

	private final DetectionEventRepository repository;
	private final ObjectMapper objectMapper;
	/** 목적지 IP를 서비스 이름으로 되돌린다. 토폴로지 엣지와 같은 규칙을 쓴다. */
	private final PeerNaming peerNaming;

	@Transactional(readOnly = true)
	public EventPageResponse list(EventQuery q) {
		if (q.cursor() != null && q.afterId() != null) {
			throw new ApiException(ErrorCode.CONFLICTING_PARAMETER,
					"cursor와 afterId는 동시에 지정할 수 없습니다.");
		}
		int size = clampSize(q.size());
		boolean ascending = q.afterId() != null;   // 갭 필링만 오름차순

		Specification<DetectionEvent> spec = buildSpec(q, ascending);
		Sort sort = Sort.by(ascending ? Sort.Direction.ASC : Sort.Direction.DESC, "eventId");
		// hasNext 판정을 위해 한 건 더 가져온다
		List<DetectionEvent> rows = repository.findAll(spec, PageRequest.of(0, size + 1, sort))
				.getContent();

		boolean hasNext = rows.size() > size;
		if (hasNext) {
			rows = rows.subList(0, size);
		}
		// 응답은 항상 최신 우선(eventId DESC) 정렬로 반환한다
		if (ascending) {
			rows = new ArrayList<>(rows);
			rows.sort((a, b) -> Long.compare(b.getEventId(), a.getEventId()));
		}

		List<EventResponse> items = peerNaming.name(rows);
		String nextCursor = hasNext && !items.isEmpty()
				? items.get(items.size() - 1).eventId() : null;
		return new EventPageResponse(items, nextCursor, hasNext, size);
	}

	@Transactional(readOnly = true)
	public EventDetailResponse detail(long eventId) {
		DetectionEvent e = repository.findById(eventId)
				.orElseThrow(() -> new ApiException(ErrorCode.EVENT_NOT_FOUND,
						"해당 탐지 이벤트가 존재하지 않습니다."));
		return EventDetailResponse.from(e, peerNaming.name(e), parsePackets(e.getPacketsJson()));
	}

	private Specification<DetectionEvent> buildSpec(EventQuery q, boolean ascending) {
		return (root, query, cb) -> {
			List<Predicate> preds = new ArrayList<>();
			if (q.cursor() != null) {
				preds.add(cb.lessThan(root.get("eventId"), q.cursor()));
			}
			if (q.afterId() != null) {
				preds.add(cb.greaterThan(root.get("eventId"), q.afterId()));
			}
			if (q.verdicts() != null && !q.verdicts().isEmpty()) {
				preds.add(root.get("verdict").in(q.verdicts()));
			}
			if (q.serviceName() != null) {
				preds.add(cb.equal(root.get("serviceName"), q.serviceName()));
			}
			if (q.podName() != null) {
				preds.add(cb.equal(root.get("podName"), q.podName()));
			}
			if (q.direction() != null) {
				preds.add(cb.equal(root.get("direction"), q.direction()));
			}
			if (q.from() != null) {
				preds.add(cb.greaterThanOrEqualTo(root.get("occurredAt"), q.from()));
			}
			if (q.to() != null) {
				preds.add(cb.lessThan(root.get("occurredAt"), q.to()));
			}
			return cb.and(preds.toArray(new Predicate[0]));
		};
	}

	private int clampSize(Integer size) {
		if (size == null) {
			return 50;
		}
		if (size < 1 || size > 200) {
			throw new ApiException(ErrorCode.INVALID_PARAMETER, "size는 1~200 범위여야 합니다.");
		}
		return size;
	}

	private JsonNode parsePackets(String json) {
		if (json == null) {
			return null;
		}
		try {
			return objectMapper.readTree(json);
		} catch (JsonProcessingException exc) {
			return null;
		}
	}

	/** 필터 파라미터 묶음. */
	public record EventQuery(
			Long cursor,
			Long afterId,
			Integer size,
			List<String> verdicts,
			String serviceName,
			String podName,
			String direction,
			OffsetDateTime from,
			OffsetDateTime to
	) {
	}

}
