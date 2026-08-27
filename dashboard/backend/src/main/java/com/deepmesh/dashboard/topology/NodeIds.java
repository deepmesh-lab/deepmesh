package com.deepmesh.dashboard.topology;

/**
 * 토폴로지 노드 식별자 규칙.
 *
 * <p>노드 id는 워크로드 이름이 아니라 <b>서비스의 짧은 이름</b>이다. K8s 워크로드는
 * auth-service·post-service처럼 접미사가 붙어 있고 텔레메트리의 serviceName도 그 값이지만,
 * 명세 1-2의 예시와 프론트의 고정 격자 배치(topology/layout.ts의 GRID)가 모두 짧은 이름을
 * 쓴다. 여기서 한 번 정규화해 양쪽이 만나게 한다.
 *
 * <p>정규화를 빼면 노드가 격자 밖으로 밀려나 화면이 무너지고, 엣지의 source·target이
 * 노드 id와 달라져 선이 끊긴다.
 */
public final class NodeIds {

	private static final String SERVICE_SUFFIX = "-service";

	/** Control Plane 합성 노드. 프론트의 CONTROL_PLANE_ID와 같은 값이어야 한다. */
	public static final String CONTROL_PLANE = "control-plane";

	private NodeIds() {
	}

	public static String of(String workloadOrServiceName) {
		if (workloadOrServiceName == null) {
			return null;
		}
		return workloadOrServiceName.endsWith(SERVICE_SUFFIX)
				? workloadOrServiceName.substring(
						0, workloadOrServiceName.length() - SERVICE_SUFFIX.length())
				: workloadOrServiceName;
	}
}
