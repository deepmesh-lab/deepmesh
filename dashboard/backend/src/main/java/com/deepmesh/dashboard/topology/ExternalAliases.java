package com.deepmesh.dashboard.topology;

import java.util.Set;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

/**
 * external로 접을 워크로드 이름(traffic-gen 등)을 한곳에서 관리한다.
 *
 * <p>traffic-gen은 클러스터 밖 사용자를 흉내 내는 부하 생성기다. 사이드카가 붙은 서비스는
 * 이 Pod와 오간 트래픽에서 상대(traffic-gen)를 관측하는데, 그대로 두면 화면에 traffic-gen
 * 상자·이름이 생긴다. external로 접으면 "외부에서 들어온 트래픽"으로 읽혀 실제 north-south에
 * 가깝다.
 *
 * <p><b>공용 빈으로 뺀 이유</b>: 별칭 규칙이 토폴로지({@link TopologyService})에만 있으면
 * 엣지는 external로 접히는데 탐지 이벤트·로그에는 traffic-gen이 그대로 남아 화면 곳곳에서
 * 이름이 어긋난다. 한곳에 모아 두 경로가 같은 규칙을 쓰게 한다.
 */
@Component
public class ExternalAliases {

	private final Set<String> aliases;

	public ExternalAliases(
			@Value("${deepmesh.topology.external-alias:traffic-gen}") String[] aliases) {
		this.aliases = Set.of(aliases);
	}

	/** 테스트·수동 조립용. */
	public static ExternalAliases of(String... aliases) {
		return new ExternalAliases(aliases);
	}

	public boolean contains(String node) {
		return node != null && aliases.contains(node);
	}

	/** 별칭이면 external로 접고, 아니면 그대로 둔다. null은 그대로 통과시킨다. */
	public String fold(String node) {
		return contains(node) ? PeerIndex.EXTERNAL_NODE : node;
	}
}
