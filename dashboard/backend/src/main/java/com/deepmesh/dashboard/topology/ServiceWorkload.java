package com.deepmesh.dashboard.topology;

/**
 * 토폴로지 노드 하나에 대응하는 K8s 워크로드 정보.
 *
 * <p>단위가 Pod가 아니라 Service다 (backend-frontend-api.md 1-2 설계 제약). replica는
 * replicaCount 배지로 표기하고 개별 Pod는 1-3절로 조회한다.
 */
public record ServiceWorkload(
		String serviceName,
		String namespace,
		NodeKind kind,
		int replicaCount,
		int readyReplicaCount,
		/** 사이드카 프록시 부착 여부. false면 탐지 대상이 아니라 counts가 null이 된다. */
		boolean proxyEnabled) {

	/** readyReplicaCount < replicaCount — 일부 Pod가 기동 중이거나 비정상. */
	public boolean degraded() {
		return readyReplicaCount < replicaCount;
	}
}
