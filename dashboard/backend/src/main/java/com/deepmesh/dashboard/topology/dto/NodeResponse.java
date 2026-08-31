package com.deepmesh.dashboard.topology.dto;

import com.deepmesh.dashboard.topology.NodeKind;
import com.deepmesh.dashboard.topology.NodeStatus;

/**
 * 토폴로지 노드 (backend-frontend-api.md 1-2).
 *
 * <p>좌표(position)를 담지 않는다. 레이아웃은 프론트가 dagre로 계산한다 — 백엔드가
 * 좌표를 정하면 화면 크기·줌 변화에 대응할 수 없다.
 */
public record NodeResponse(
		String id,
		String serviceName,
		String namespace,
		NodeKind kind,
		int replicaCount,
		int readyReplicaCount,
		boolean proxyEnabled,
		NodeStatus status,
		/** proxyEnabled=false면 null. 0이 아니다 — "감시 대상 아님"과 "사건 없음"은 다르다. */
		CountsResponse counts) {
}
