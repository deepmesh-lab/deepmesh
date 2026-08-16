package com.deepmesh.dashboard.event.dto;

import java.util.List;

/** backend-frontend-api.md 커서 기반 페이지네이션 응답. */
public record EventPageResponse(
		List<EventResponse> items,
		String nextCursor,
		boolean hasNext,
		int size
) {
}
