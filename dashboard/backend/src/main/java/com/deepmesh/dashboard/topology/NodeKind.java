package com.deepmesh.dashboard.topology;

/**
 * 토폴로지 노드 종류 (backend-frontend-api.md 1-2).
 *
 * <p>SERVICE만 프록시가 붙어 자기 통계를 갖는다. 나머지는 관측 주체가 없어 counts가
 * null이다 — 0이 아니다. 0은 "감시했으나 사건 없음"이고 null은 "감시 대상 아님"이라,
 * 구분하지 않으면 미감시 구간을 안전한 구간으로 오인하게 된다.
 */
public enum NodeKind {

	/** 사이드카가 부착된 MSA 서비스. */
	SERVICE,
	/** MySQL 등 데이터 저장소. 사이드카 미부착. */
	DATASTORE,
	/** Kubernetes API Server. 시나리오 1의 Drop 대상. */
	K8S_API,
	/** 클러스터 외부. K8s 리소스가 아닌 합성 노드. */
	EXTERNAL
}
