package com.deepmesh.dashboard.topology;

/**
 * 토폴로지 노드 종류 (backend-frontend-api.md 1-2).
 *
 * <p>SERVICE와 GATEWAY만 프록시가 붙어 자기 통계를 갖는다. 나머지는 관측 주체가 없어 counts가
 * null이다 — 0이 아니다. 0은 "감시했으나 사건 없음"이고 null은 "감시 대상 아님"이라,
 * 구분하지 않으면 미감시 구간을 안전한 구간으로 오인하게 된다.
 */
public enum NodeKind {

	/** 사이드카가 부착된 MSA 서비스. */
	SERVICE,
	/**
	 * 브라우저를 마주보는 진입점. 사이드카가 붙어 있어 SERVICE와 관측 방식은 같다.
	 *
	 * <p>따로 둔 이유는 트래픽의 성격이 다르기 때문이다. 다른 SERVICE의 판정은 서비스
	 * 사이의 호출이지만, 이 노드의 판정은 대부분 <b>브라우저에게 보낸 응답</b>이라
	 * 상대가 클러스터 밖(external)이다. 같은 모양으로 그리면 "왜 이 노드만 external로
	 * 나가는 선이 많은가"가 설명되지 않는다.
	 *
	 * <p>어느 워크로드가 여기 속하는지는 클러스터 구성에서 알 수 없어 설정으로 지정한다
	 * ({@code deepmesh.topology.gateway}). counts·status 계산은 SERVICE와 완전히 같다.
	 */
	GATEWAY,
	/** MySQL 등 데이터 저장소. 사이드카 미부착. */
	DATASTORE,
	/** Kubernetes API Server. 시나리오 1의 Drop 대상. */
	K8S_API,
	/** 클러스터 외부. K8s 리소스가 아닌 합성 노드. */
	EXTERNAL,
	/**
	 * Control Plane (Request Verifier + Pod Info Provider).
	 *
	 * <p>명세 1-2의 enum에 없는 값이다. Control Plane은 master 노드의 호스트 프로세스라
	 * K8s 워크로드로 잡히지 않는데, 프론트는 이걸 별도 상자로 그리도록 만들어져 있다
	 * (topology/layout.ts의 CONTROL_PLANE_PARTS). 백엔드가 합성해 주지 않으면 그 자리가
	 * 빈다.
	 */
	CONTROL_PLANE
}
