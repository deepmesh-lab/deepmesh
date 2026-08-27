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

	public void reset() {
		workloads.clear();
		pods.clear();
		ipToService.clear();
		kinds.clear();
	}

	public FakeClusterTopologySource workload(String name, int replicas, int ready, boolean proxied) {
		workloads.add(new ServiceWorkload(name, "default",
				proxied ? NodeKind.SERVICE : NodeKind.DATASTORE, replicas, ready, proxied));
		kinds.put(name, proxied ? NodeKind.SERVICE : NodeKind.DATASTORE);
		return this;
	}

	public FakeClusterTopologySource pod(String service, String podName, String podIp,
			boolean ready, boolean proxyReady) {
		pods.computeIfAbsent(service, k -> new ArrayList<>()).add(new PodDetail(
				podName, podIp, "worker-1", "Running", ready,
				OffsetDateTime.parse("2026-08-08T13:00:00+09:00"), proxyReady));
		ipToService.put(podIp, service);
		return this;
	}

	public FakeClusterTopologySource serviceIp(String ip, String service) {
		ipToService.put(ip, service);
		return this;
	}

	@Override
	public List<ServiceWorkload> workloads(String namespace) {
		return List.copyOf(workloads);
	}

	@Override
	public List<PodDetail> pods(String namespace, String serviceName) {
		return pods.get(serviceName);
	}

	@Override
	public String activeReplicaSetName(String namespace, String serviceName) {
		return serviceName + "-abc123";
	}

	@Override
	public PeerIndex peerIndex(String namespace) {
		return new PeerIndex(Map.copyOf(ipToService), Map.copyOf(kinds), apiServerIp);
	}
}
