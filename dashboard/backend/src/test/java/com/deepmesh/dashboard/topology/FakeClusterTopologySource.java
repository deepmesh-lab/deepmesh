package com.deepmesh.dashboard.topology;

import java.time.OffsetDateTime;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/** 클러스터 없이 토폴로지를 검증하기 위한 대역. 테스트가 원하는 클러스터 모습을 직접 세운다. */
public class FakeClusterTopologySource implements ClusterTopologySource {

	private final List<ServiceWorkload> workloads = new ArrayList<>();
	private final Map<String, List<PodDetail>> pods = new HashMap<>();
	private final Map<String, String> ipToService = new HashMap<>();
	private final Map<String, NodeKind> kinds = new HashMap<>();
	private String apiServerIp = "10.96.0.1";
	private String controlPlaneIp = "192.168.56.10";

	public void reset() {
		workloads.clear();
		pods.clear();
		ipToService.clear();
		kinds.clear();
	}

	/**
	 * 워크로드 이름을 받아 노드 id로 정규화해 담는다 — 실제 구현이 하는 일과 같다.
	 * 대역이 이걸 빠뜨리면 테스트만 통과하고 클러스터에서는 노드 id가 어긋난다.
	 */
	public FakeClusterTopologySource workload(String name, int replicas, int ready, boolean proxied) {
		String id = NodeIds.of(name);
		workloads.add(new ServiceWorkload(id, "default",
				proxied ? NodeKind.SERVICE : NodeKind.DATASTORE, replicas, ready, proxied));
		kinds.put(id, proxied ? NodeKind.SERVICE : NodeKind.DATASTORE);
		return this;
	}

	public FakeClusterTopologySource pod(String service, String podName, String podIp,
			boolean ready, boolean proxyReady) {
		pods.computeIfAbsent(NodeIds.of(service), k -> new ArrayList<>()).add(new PodDetail(
				podName, podIp, "worker-1", "Running", ready,
				OffsetDateTime.parse("2026-08-08T13:00:00+09:00"), proxyReady));
		ipToService.put(podIp, NodeIds.of(service));
		return this;
	}

	public FakeClusterTopologySource serviceIp(String ip, String service) {
		ipToService.put(ip, NodeIds.of(service));
		return this;
	}

	@Override
	public List<ServiceWorkload> workloads(String namespace) {
		return List.copyOf(workloads);
	}

	@Override
	public List<PodDetail> pods(String namespace, String serviceName) {
		return pods.get(NodeIds.of(serviceName));
	}

	@Override
	public String activeReplicaSetName(String namespace, String serviceName) {
		return NodeIds.of(serviceName) + "-abc123";
	}

	@Override
	public PeerIndex peerIndex(String namespace) {
		return new PeerIndex(Map.copyOf(ipToService), Map.copyOf(kinds), apiServerIp, controlPlaneIp);
	}
}
