package com.deepmesh.dashboard.topology;

import com.deepmesh.dashboard.common.ApiException;
import com.deepmesh.dashboard.common.ErrorCode;
import io.fabric8.kubernetes.api.model.Container;
import io.fabric8.kubernetes.api.model.ContainerStatus;
import io.fabric8.kubernetes.api.model.Pod;
import io.fabric8.kubernetes.api.model.Service;
import io.fabric8.kubernetes.api.model.apps.Deployment;
import io.fabric8.kubernetes.api.model.apps.StatefulSet;
import io.fabric8.kubernetes.client.KubernetesClient;
import io.fabric8.kubernetes.client.KubernetesClientException;
import java.time.OffsetDateTime;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;

/**
 * fabric8로 K8s를 읽는 구현.
 *
 * <p>사이드카 부착 여부는 컨테이너 이름으로 판별한다 — Control Plane의 Pod 디스커버리와
 * 같은 기준이어야 한다(control_plane.py의 SIDECAR_CONTAINER). 두 곳이 다른 기준을 쓰면
 * 대시보드에는 감시 중으로 보이는 Pod에 주소록이 배포되지 않는 상태가 생긴다.
 *
 * <p>K8s 호출 실패는 503 DATA_SOURCE_UNAVAILABLE로 바꾼다. 빈 토폴로지를 돌려주면
 * 화면상 "아무 서비스도 없음"과 구분되지 않아, 클러스터 장애가 평온한 화면으로 보인다.
 */
@Slf4j
@RequiredArgsConstructor
public class Fabric8ClusterTopologySource implements ClusterTopologySource {

	/** 사이드카 컨테이너 이름. 매니페스트·Control Plane과 같은 값이어야 한다. */
	static final String SIDECAR_CONTAINER = "reverse-proxy";

	private final KubernetesClient client;

	/**
	 * Control Plane의 호스트(예: 192.168.56.10). configmap의 CONTROL_PLANE_URL과 같은
	 * 곳을 가리켜야 사이드카가 그리로 보낸 트래픽이 control-plane 노드로 되돌아온다.
	 */
	private final String controlPlaneHost;

	@Override
	public List<ServiceWorkload> workloads(String namespace) {
		return guard(() -> {
			Map<String, List<Pod>> podsByApp = podsByApp(namespace);
			List<ServiceWorkload> out = new ArrayList<>();
			for (Deployment deployment : client.apps().deployments().inNamespace(namespace).list().getItems()) {
				out.add(toWorkload(
						deployment.getMetadata().getName(), namespace, podsByApp,
						deployment.getSpec() == null ? null : deployment.getSpec().getReplicas(),
						deployment.getStatus() == null ? null : deployment.getStatus().getReadyReplicas()));
			}
			// mysql은 StatefulSet이다. 빠뜨리면 DATASTORE 노드가 통째로 사라져, 실제로는
			// 관측 대상이 아닌 구간이 토폴로지에서 아예 안 보이게 된다.
			for (StatefulSet set : client.apps().statefulSets().inNamespace(namespace).list().getItems()) {
				out.add(toWorkload(
						set.getMetadata().getName(), namespace, podsByApp,
						set.getSpec() == null ? null : set.getSpec().getReplicas(),
						set.getStatus() == null ? null : set.getStatus().getReadyReplicas()));
			}
			return out;
		});
	}

	@Override
	public List<PodDetail> pods(String namespace, String serviceName) {
		return guard(() -> {
			// 호출부는 노드 id(짧은 이름)를 준다. 워크로드 이름은 접미사가 붙어 있을 수
			// 있으므로 정규화한 키로 찾는다.
			Map<String, List<Pod>> byApp = new HashMap<>();
			podsByApp(namespace).forEach((app, pods) -> byApp.put(NodeIds.of(app), pods));
			List<Pod> pods = byApp.get(NodeIds.of(serviceName));
			if (pods == null) {
				return null;   // 서비스 자체가 없다 -> 호출부가 404로 바꾼다
			}
			List<PodDetail> out = new ArrayList<>();
			for (Pod pod : pods) {
				out.add(new PodDetail(
						pod.getMetadata().getName(),
						pod.getStatus() == null ? null : pod.getStatus().getPodIP(),
						pod.getSpec() == null ? null : pod.getSpec().getNodeName(),
						pod.getStatus() == null ? "Unknown" : pod.getStatus().getPhase(),
						containerReady(pod, null),
						parseTime(pod.getStatus() == null ? null : pod.getStatus().getStartTime()),
						containerReady(pod, SIDECAR_CONTAINER)));
			}
			return out;
		});
	}

	@Override
	public String activeReplicaSetName(String namespace, String serviceName) {
		return guard(() -> client.apps().replicaSets().inNamespace(namespace).list().getItems().stream()
				.filter(rs -> NodeIds.of(rs.getMetadata().getName()).startsWith(NodeIds.of(serviceName) + "-")
						|| rs.getMetadata().getName().startsWith(serviceName + "-"))
				// 롤링 업데이트 중이면 여럿이다. 실제로 Pod를 갖고 있는 최신 것을 고른다.
				.filter(rs -> rs.getSpec() != null && nullSafe(rs.getSpec().getReplicas()) > 0)
				.map(rs -> rs.getMetadata().getName())
				.max(String::compareTo)
				.orElse(null));
	}

	@Override
	public PeerIndex peerIndex(String namespace) {
		return guard(() -> {
			Map<String, String> ipToService = new HashMap<>();
			Map<String, NodeKind> kinds = new HashMap<>();
			String apiServerIp = null;

			for (Map.Entry<String, List<Pod>> entry : podsByApp(namespace).entrySet()) {
				String nodeId = NodeIds.of(entry.getKey());
				boolean proxied = entry.getValue().stream()
						.anyMatch(Fabric8ClusterTopologySource::hasSidecar);
				// 사이드카가 없으면 DATASTORE로 접는다. 명세의 kind 열거에 "감시 대상이
				// 아닌 클러스터 내 워크로드"를 따로 두지 않았고, 화면 동작을 가르는 것은
				// kind가 아니라 proxyEnabled=false -> counts null -> UNMONITORED다.
				kinds.put(nodeId, proxied ? NodeKind.SERVICE : NodeKind.DATASTORE);
				for (Pod pod : entry.getValue()) {
					String ip = pod.getStatus() == null ? null : pod.getStatus().getPodIP();
					if (ip != null) {
						ipToService.put(ip, nodeId);
					}
				}
			}

			// ClusterIP도 같은 서비스로 되돌린다. 목적지가 Service 이름으로 해석돼 나가면
			// dstIp가 Pod IP가 아니라 ClusterIP다.
			for (Service service : client.services().inNamespace(namespace).list().getItems()) {
				String ip = service.getSpec() == null ? null : service.getSpec().getClusterIP();
				if (ip == null || "None".equals(ip)) {
					continue;   // headless service
				}
				String name = nodeIdOf(service);
				ipToService.putIfAbsent(ip, name);
				kinds.putIfAbsent(name, NodeKind.DATASTORE);
			}

			Service kubernetes = client.services().inNamespace("default").withName("kubernetes").get();
			if (kubernetes != null && kubernetes.getSpec() != null) {
				apiServerIp = kubernetes.getSpec().getClusterIP();
			}
			return new PeerIndex(ipToService, kinds, apiServerIp, controlPlaneHost);
		});
	}

	private static ServiceWorkload toWorkload(
			String name, String namespace, Map<String, List<Pod>> podsByApp,
			Integer replicas, Integer readyReplicas) {
		List<Pod> pods = podsByApp.getOrDefault(name, List.of());
		boolean proxied = pods.stream().anyMatch(Fabric8ClusterTopologySource::hasSidecar);
		// 노드 id는 워크로드 이름이 아니라 짧은 이름이다 (NodeIds 참고).
		return new ServiceWorkload(NodeIds.of(name), namespace,
				proxied ? NodeKind.SERVICE : NodeKind.DATASTORE,
				nullSafe(replicas), nullSafe(readyReplicas), proxied);
	}

	private Map<String, List<Pod>> podsByApp(String namespace) {
		Map<String, List<Pod>> byApp = new HashMap<>();
		for (Pod pod : client.pods().inNamespace(namespace).list().getItems()) {
			String app = pod.getMetadata().getLabels() == null
					? null : pod.getMetadata().getLabels().get("app");
			if (app != null) {
				byApp.computeIfAbsent(app, k -> new ArrayList<>()).add(pod);
			}
		}
		return byApp;
	}

	private static boolean hasSidecar(Pod pod) {
		if (pod.getSpec() == null || pod.getSpec().getContainers() == null) {
			return false;
		}
		return pod.getSpec().getContainers().stream()
				.map(Container::getName).anyMatch(SIDECAR_CONTAINER::equals);
	}

	/** name이 null이면 Pod 전체 Ready, 아니면 그 컨테이너의 Ready. */
	private static boolean containerReady(Pod pod, String name) {
		if (pod.getStatus() == null || pod.getStatus().getContainerStatuses() == null) {
			return false;
		}
		List<ContainerStatus> statuses = pod.getStatus().getContainerStatuses();
		if (name == null) {
			return !statuses.isEmpty() && statuses.stream().allMatch(s -> Boolean.TRUE.equals(s.getReady()));
		}
		return statuses.stream()
				.filter(s -> name.equals(s.getName()))
				.anyMatch(s -> Boolean.TRUE.equals(s.getReady()));
	}

	/**
	 * Service를 노드 id로 맞춘다.
	 *
	 * <p>노드 id는 워크로드 이름이고, 이벤트의 serviceName(사이드카 SERVICE_NAME env)과
	 * 같은 값이어야 엣지의 source·target이 이어진다. Service 이름은 그것과 다를 수 있어
	 * (frontend 워크로드의 Service는 frontend-service다) 이름을 자르는 대신 selector의
	 * app 라벨을 본다 — 매니페스트가 워크로드 이름을 그대로 app 라벨로 쓴다.
	 */
	private static String nodeIdOf(Service service) {
		if (service.getSpec() != null && service.getSpec().getSelector() != null) {
			String app = service.getSpec().getSelector().get("app");
			if (app != null) {
				return NodeIds.of(app);
			}
		}
		return NodeIds.of(service.getMetadata().getName());
	}

	private static int nullSafe(Integer value) {
		return value == null ? 0 : value;
	}

	private static OffsetDateTime parseTime(String value) {
		return value == null ? null : OffsetDateTime.parse(value);
	}

	private <T> T guard(java.util.function.Supplier<T> call) {
		try {
			return call.get();
		} catch (KubernetesClientException exc) {
			log.warn("K8s 조회 실패: {}", exc.getMessage());
			throw new ApiException(ErrorCode.DATA_SOURCE_UNAVAILABLE,
					"클러스터 정보를 읽지 못했습니다.");
		}
	}
}
