package com.deepmesh.dashboard.topology;

import com.deepmesh.dashboard.common.ApiException;
import com.deepmesh.dashboard.common.ErrorCode;
import com.deepmesh.dashboard.common.TimeRange;
import com.deepmesh.dashboard.event.DetectionEvent;
import com.deepmesh.dashboard.event.DetectionEventRepository;
import com.deepmesh.dashboard.stats.StatsBucket;
import com.deepmesh.dashboard.stats.StatsBucketRepository;
import com.deepmesh.dashboard.topology.dto.CountsResponse;
import com.deepmesh.dashboard.topology.dto.EdgeResponse;
import com.deepmesh.dashboard.topology.dto.NodeResponse;
import com.deepmesh.dashboard.topology.dto.ServiceDetailResponse;
import com.deepmesh.dashboard.topology.dto.TopologyResponse;
import java.time.Clock;
import java.time.OffsetDateTime;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/**
 * backend-frontend-api.md 1-2·1-3. 토폴로지 스냅샷과 서비스별 replica 상세.
 *
 * <p>노드는 K8s에서 오고 엣지는 관측 데이터에서 온다. 그래서 트래픽이 전혀 없는 서비스도
 * 노드로는 나타나지만, 엣지는 실제로 관측된 통신만 나타난다 — 시나리오 1의
 * post→kubernetes 엣지가 공격 시점에 처음 생기는 것이 그 성질이다.
 *
 * <p>엣지 counts는 두 출처를 합친다. benign은 peer_benign_bucket에서(개별 이벤트가 없다),
 * cleared/drop/relay는 detection_event에서 온다.
 */
@Service
public class TopologyService {

	/**
	 * 엣지 상한. 넘으면 total 상위만 남기고 나머지는 EXTERNAL 노드로 접는다.
	 *
	 * <p>포트 스캔은 서로 다른 목적지를 수천 개 만든다. 그대로 엣지가 되면 React Flow가
	 * 멈춘다 — 탐지는 성공했는데 그걸 볼 화면이 죽는 형태다. 프록시가 아니라 여기에 두는
	 * 이유는 benign·attack 두 출처가 여기서 합쳐지기 때문이다.
	 */
	static final int MAX_EDGES = 50;

	/**
	 * namespace 파라미터가 없을 때 볼 곳. 명세는 default를 기본값으로 적었지만 이 클러스터의
	 * 워크로드는 deepmesh에 있다 — default를 보면 아무것도 없거나 RBAC에 막힌다.
	 */
	private final String defaultNamespace;

	private final ClusterTopologySource cluster;
	private final DetectionEventRepository eventRepository;
	private final StatsBucketRepository statsRepository;
	private final PeerBenignBucketRepository peerRepository;
	private final Clock clock;

	public TopologyService(
			@Value("${deepmesh.namespace:deepmesh}") String defaultNamespace,
			ClusterTopologySource cluster,
			DetectionEventRepository eventRepository,
			StatsBucketRepository statsRepository,
			PeerBenignBucketRepository peerRepository,
			Clock clock) {
		this.defaultNamespace = defaultNamespace;
		this.cluster = cluster;
		this.eventRepository = eventRepository;
		this.statsRepository = statsRepository;
		this.peerRepository = peerRepository;
		this.clock = clock;
	}

	@Transactional(readOnly = true)
	public TopologyResponse topology(String timeRange, String namespace) {
		OffsetDateTime now = now();
		TimeRange range = TimeRange.of(timeRange, now);
		String ns = namespace == null ? defaultNamespace : namespace;

		List<ServiceWorkload> workloads = cluster.workloads(ns);
		PeerIndex peers = cluster.peerIndex(ns);

		Map<String, VerdictCounts> byService = countsByService(range);
		List<EdgeResponse> edges = buildEdges(range, peers);

		List<NodeResponse> nodes = new ArrayList<>();
		Set<String> known = new HashSet<>();
		for (ServiceWorkload workload : workloads) {
			known.add(workload.serviceName());
			nodes.add(toNode(workload, byService.get(workload.serviceName())));
		}
		// Control Plane은 master 노드의 호스트 프로세스라 K8s 워크로드로 잡히지 않는다.
		// 합성해 주지 않으면 프론트의 고정 격자에서 그 자리가 빈다.
		if (known.add(NodeIds.CONTROL_PLANE)) {
			nodes.add(syntheticNode(NodeIds.CONTROL_PLANE, ns, NodeKind.CONTROL_PLANE));
		}
		// 엣지가 가리키는데 워크로드로는 안 잡히는 목적지(K8s API, external, 다른 NS)를
		// 합성 노드로 채운다. 없으면 프론트에서 끊긴 엣지가 된다.
		for (EdgeResponse edge : edges) {
			if (known.add(edge.target())) {
				nodes.add(syntheticNode(edge.target(), ns, peers.kindOf(edge.target())));
			}
		}
		return new TopologyResponse(now, range.label(), ns, nodes, edges);
	}

	@Transactional(readOnly = true)
	public ServiceDetailResponse serviceDetail(String serviceName, String timeRange, String namespace) {
		OffsetDateTime now = now();
		TimeRange range = TimeRange.of(timeRange, now);
		String ns = namespace == null ? defaultNamespace : namespace;

		List<PodDetail> pods = cluster.pods(ns, serviceName);
		if (pods == null) {
			throw new ApiException(ErrorCode.SERVICE_NOT_FOUND,
					"해당 서비스가 존재하지 않습니다: " + serviceName);
		}

		Map<String, VerdictCounts> byPod = countsByPod(range, serviceName);
		Map<String, String> modelIds = modelIdsByPod(range, serviceName);

		List<ServiceDetailResponse.PodResponse> out = new ArrayList<>();
		for (PodDetail pod : pods) {
			VerdictCounts counts = byPod.getOrDefault(pod.podName(), VerdictCounts.zero());
			out.add(new ServiceDetailResponse.PodResponse(
					pod.podName(), pod.podIp(), pod.nodeName(), pod.phase(), pod.ready(),
					pod.startedAt(), pod.proxyReady(),
					modelIds.get(pod.podName()),
					CountsResponse.of(counts),
					podStatus(pod, counts)));
		}
		return new ServiceDetailResponse(serviceName, ns,
				cluster.activeReplicaSetName(ns, serviceName), range.label(), now, out);
	}

	// ── 노드 ────────────────────────────────────────────────────────────────

	private NodeResponse toNode(ServiceWorkload workload, VerdictCounts counts) {
		VerdictCounts resolved = counts == null ? VerdictCounts.zero() : counts;
		return new NodeResponse(
				workload.serviceName(), workload.serviceName(), workload.namespace(),
				workload.kind(), workload.replicaCount(), workload.readyReplicaCount(),
				workload.proxyEnabled(),
				nodeStatus(workload, resolved),
				// 감시 대상이 아니면 0이 아니라 null이다. 0으로 두면 미감시 구간이
				// "사건 없음"으로 읽힌다.
				workload.proxyEnabled() ? CountsResponse.of(resolved) : null);
	}

	private NodeResponse syntheticNode(String id, String namespace, NodeKind kind) {
		// K8s 리소스가 아니므로 replica 개념이 없고, 프록시도 없어 counts가 null이다.
		return new NodeResponse(id, id, namespace, kind, 1, 1, false,
				NodeStatus.UNMONITORED, null);
	}

	/** 우선순위: UNMONITORED > COMPROMISED > DEGRADED > HEALTHY (명세 1-2). */
	private NodeStatus nodeStatus(ServiceWorkload workload, VerdictCounts counts) {
		if (!workload.proxyEnabled()) {
			return NodeStatus.UNMONITORED;
		}
		if (counts.hasBlocked()) {
			return NodeStatus.COMPROMISED;
		}
		if (workload.degraded()) {
			return NodeStatus.DEGRADED;
		}
		return NodeStatus.HEALTHY;
	}

	private NodeStatus podStatus(PodDetail pod, VerdictCounts counts) {
		if (!pod.proxyReady()) {
			return NodeStatus.UNMONITORED;
		}
		if (counts.hasBlocked()) {
			return NodeStatus.COMPROMISED;
		}
		if (!pod.ready()) {
			return NodeStatus.DEGRADED;
		}
		return NodeStatus.HEALTHY;
	}

	// ── 엣지 ────────────────────────────────────────────────────────────────

	private List<EdgeResponse> buildEdges(TimeRange range, PeerIndex peers) {
		Map<String, EdgeAccumulator> byId = new HashMap<>();

		// benign — 개별 이벤트가 없어 이 집계만이 근거다
		for (PeerBenignBucket bucket : peerRepository
				.findByWindowToGreaterThanEqualAndWindowToLessThan(range.from(), range.to())) {
			String target = PeerBenignBucket.OTHER_DST_IP.equals(bucket.getDstIp())
					? PeerIndex.EXTERNAL_NODE
					: peers.resolve(bucket.getDstIp(), null);
			accumulator(byId, NodeIds.of(bucket.getServiceName()), target).addBenign(bucket.getBenign());
		}

		// cleared/drop/relay — 이벤트가 dstIp를 갖고 온다
		for (DetectionEvent event : eventRepository
				.findByOccurredAtGreaterThanEqualAndOccurredAtLessThan(range.from(), range.to())) {
			String target = peers.resolve(event.getDstIp(), event.getDstPort());
			accumulator(byId, NodeIds.of(event.getServiceName()), target).addEvent(event);
		}

		List<EdgeAccumulator> sorted = new ArrayList<>(byId.values());
		sorted.sort(Comparator.comparingLong((EdgeAccumulator a) -> a.counts.total()).reversed());
		return fold(sorted);
	}

	/** 상위 MAX_EDGES만 남기고 나머지는 source별 EXTERNAL 엣지 하나로 접는다. */
	private List<EdgeResponse> fold(List<EdgeAccumulator> sorted) {
		List<EdgeResponse> out = new ArrayList<>();
		Map<String, EdgeAccumulator> folded = new HashMap<>();
		for (int i = 0; i < sorted.size(); i++) {
			EdgeAccumulator edge = sorted.get(i);
			if (i < MAX_EDGES) {
				out.add(edge.toResponse(0));
				continue;
			}
			EdgeAccumulator bucket = folded.computeIfAbsent(edge.source,
					s -> new EdgeAccumulator(s, PeerIndex.EXTERNAL_NODE));
			bucket.absorb(edge);
		}
		for (EdgeAccumulator bucket : folded.values()) {
			out.add(bucket.toResponse(bucket.absorbed));
		}
		return out;
	}

	private EdgeAccumulator accumulator(Map<String, EdgeAccumulator> byId, String source, String target) {
		return byId.computeIfAbsent(source + "->" + target, k -> new EdgeAccumulator(source, target));
	}

	/** 엣지 하나를 쌓는 동안의 가변 상태. 응답으로 나갈 때 record로 굳는다. */
	private static final class EdgeAccumulator {
		private final String source;
		private final String target;
		private VerdictCounts counts = VerdictCounts.zero();
		private String lastVerdict = "FORWARD";
		private OffsetDateTime lastEventAt;
		private int absorbed;

		EdgeAccumulator(String source, String target) {
			this.source = source;
			this.target = target;
		}

		void addBenign(long benign) {
			counts = counts.plus(new VerdictCounts(benign, 0, 0, 0));
		}

		void addEvent(DetectionEvent event) {
			counts = counts.plus(switch (event.getCategory() == null ? "" : event.getCategory()) {
				case "cleared" -> new VerdictCounts(0, 1, 0, 0);
				case "drop" -> new VerdictCounts(0, 0, 1, 0);
				case "relay" -> new VerdictCounts(0, 0, 0, 1);
				default -> VerdictCounts.zero();
			});
			if (lastEventAt == null || event.getOccurredAt().isAfter(lastEventAt)) {
				lastEventAt = event.getOccurredAt();
				lastVerdict = event.getVerdict();
			}
		}

		void absorb(EdgeAccumulator other) {
			counts = counts.plus(other.counts);
			absorbed++;
			if (other.lastEventAt != null
					&& (lastEventAt == null || other.lastEventAt.isAfter(lastEventAt))) {
				lastEventAt = other.lastEventAt;
				lastVerdict = other.lastVerdict;
			}
		}

		EdgeResponse toResponse(int foldedPeerCount) {
			return new EdgeResponse(source + "->" + target, source, target, "TCP",
					counts.total(), CountsResponse.of(counts), lastVerdict, lastEventAt,
					foldedPeerCount);
		}
	}

	// ── 집계 ────────────────────────────────────────────────────────────────

	private Map<String, VerdictCounts> countsByService(TimeRange range) {
		Map<String, VerdictCounts> out = new HashMap<>();
		for (StatsBucket bucket : statsRepository
				.findByWindowToGreaterThanEqualAndWindowToLessThan(range.from(), range.to())) {
			out.merge(NodeIds.of(bucket.getServiceName()), toCounts(bucket), VerdictCounts::plus);
		}
		return out;
	}

	private Map<String, VerdictCounts> countsByPod(TimeRange range, String serviceName) {
		Map<String, VerdictCounts> out = new HashMap<>();
		for (StatsBucket bucket : statsRepository
				.findByWindowToGreaterThanEqualAndWindowToLessThan(range.from(), range.to())) {
			if (serviceName.equals(NodeIds.of(bucket.getServiceName())) && bucket.getPodName() != null) {
				out.merge(bucket.getPodName(), toCounts(bucket), VerdictCounts::plus);
			}
		}
		return out;
	}

	/** Pod별 modelId. 개별 이벤트에만 실려 오므로 공격이 한 번도 없던 Pod는 null이다. */
	private Map<String, String> modelIdsByPod(TimeRange range, String serviceName) {
		Map<String, String> out = new HashMap<>();
		for (DetectionEvent event : eventRepository
				.findByOccurredAtGreaterThanEqualAndOccurredAtLessThan(range.from(), range.to())) {
			if (serviceName.equals(NodeIds.of(event.getServiceName())) && event.getModelId() != null) {
				out.putIfAbsent(event.getPodName(), event.getModelId());
			}
		}
		return out;
	}

	private static VerdictCounts toCounts(StatsBucket bucket) {
		return new VerdictCounts(bucket.getBenign(), bucket.getCleared(),
				bucket.getDropCount(), bucket.getRelay());
	}

	private OffsetDateTime now() {
		return OffsetDateTime.now(clock);
	}
}
