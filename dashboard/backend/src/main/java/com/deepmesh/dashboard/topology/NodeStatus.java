package com.deepmesh.dashboard.topology;

/**
 * 토폴로지 노드 상태 (backend-frontend-api.md 1-2).
 *
 * <p>선언 순서가 곧 판정 우선순위다. 위에서부터 먼저 맞는 것을 쓴다.
 */
public enum NodeStatus {

	/**
	 * 프록시가 없어 감시 대상이 아니다.
	 *
	 * <p>최우선으로 둔다 — 감시하지 않는 노드를 "정상"으로 표기하면 안 된다.
	 */
	UNMONITORED,
	/** 집계 구간 내 drop + relay >= 1. */
	COMPROMISED,
	/** readyReplicaCount < replicaCount. 일부 Pod가 기동 중이거나 비정상. */
	DEGRADED,
	/** 위 어디에도 해당하지 않음. */
	HEALTHY
}
