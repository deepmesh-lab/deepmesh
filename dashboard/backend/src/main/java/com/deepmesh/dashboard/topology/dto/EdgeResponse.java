package com.deepmesh.dashboard.topology.dto;

import java.time.OffsetDateTime;

/**
 * 관측된 통신 경로 (backend-frontend-api.md 1-2).
 *
 * <p>source의 프록시가 관측 주체다. 탐지가 egress 전용이라 frontend→post 통신은
 * frontend 프록시만 이벤트를 만든다 — 이중 집계가 원천적으로 생기지 않는다.
 */
public record EdgeResponse(
		String id,
		String source,
		String target,
		String protocol,
		long total,
		/** 엣지는 항상 관측된 통신이므로 null이 아니다. */
		CountsResponse counts,
		/** FORWARD | DROP | RELAY. 관측된 공격 이벤트가 없으면 FORWARD. */
		String lastVerdict,
		OffsetDateTime lastEventAt,
		/**
		 * 상한에 걸려 이 엣지로 접힌 목적지 수. 0이면 접힌 것이 없다.
		 *
		 * <p>명세에 없는 필드다. 스캔 때 엣지가 수천 개로 늘어나는 것을 막으려면 접어야
		 * 하는데, 접고 나면 "목적지가 많았다"는 사실이 화면에서 사라진다. 그 신호를
		 * 대신 나른다.
		 */
		int foldedPeerCount) {
}
