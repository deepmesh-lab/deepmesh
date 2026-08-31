package com.deepmesh.dashboard.topology;

import java.util.List;

/**
 * 토폴로지가 K8s에서 읽어야 하는 것만 추린 경계.
 *
 * <p>fabric8을 직접 쓰지 않고 이 인터페이스를 통하는 이유는 두 가지다. 하나는 테스트가
 * 클러스터 없이 돌아야 하기 때문이고, 다른 하나는 K8s에 닿지 못하는 실행 환경(로컬 개발)
 * 에서 앱이 뜨긴 하되 토폴로지 계열만 503으로 떨어지게 하기 위함이다.
 */
public interface ClusterTopologySource {

	/** 네임스페이스의 서비스 워크로드. 트래픽이 없는 서비스도 포함한다. */
	List<ServiceWorkload> workloads(String namespace);

	/** 한 서비스의 Pod 목록. 서비스가 없으면 빈 목록이 아니라 null을 돌려준다. */
	List<PodDetail> pods(String namespace, String serviceName);

	/** 현재 활성 ReplicaSet 이름. 없으면 null. */
	String activeReplicaSetName(String namespace, String serviceName);

	/** IP를 노드로 되돌리는 색인. 엣지의 target을 정하는 데 쓴다. */
	PeerIndex peerIndex(String namespace);
}
