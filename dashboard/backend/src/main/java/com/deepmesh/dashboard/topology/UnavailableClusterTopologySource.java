package com.deepmesh.dashboard.topology;

import com.deepmesh.dashboard.common.ApiException;
import com.deepmesh.dashboard.common.ErrorCode;
import java.util.List;

/**
 * K8s를 쓰지 않는 실행(로컬 개발·테스트)에서 토폴로지 계열만 503으로 떨어뜨린다.
 *
 * <p>빈 토폴로지를 돌려주지 않는 이유는 화면상 "아무 서비스도 없음"과 구분되지 않기
 * 때문이다. 클러스터에 닿지 못하는 상태가 평온한 화면으로 보이면 안 된다.
 */
public class UnavailableClusterTopologySource implements ClusterTopologySource {

	@Override
	public List<ServiceWorkload> workloads(String namespace) {
		throw unavailable();
	}

	@Override
	public List<PodDetail> pods(String namespace, String serviceName) {
		throw unavailable();
	}

	@Override
	public String activeReplicaSetName(String namespace, String serviceName) {
		throw unavailable();
	}

	@Override
	public PeerIndex peerIndex(String namespace) {
		throw unavailable();
	}

	private static ApiException unavailable() {
		return new ApiException(ErrorCode.DATA_SOURCE_UNAVAILABLE,
				"Kubernetes 연동이 꺼져 있어 토폴로지를 제공할 수 없습니다.");
	}
}
