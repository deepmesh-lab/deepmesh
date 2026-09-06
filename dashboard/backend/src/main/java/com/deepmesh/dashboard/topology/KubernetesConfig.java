package com.deepmesh.dashboard.topology;

import io.fabric8.kubernetes.client.KubernetesClient;
import io.fabric8.kubernetes.client.KubernetesClientBuilder;
import java.util.Arrays;
import java.util.Set;
import org.springframework.beans.factory.annotation.Value;
import lombok.extern.slf4j.Slf4j;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/**
 * K8s 연동 배선.
 *
 * <p>클러스터 안에서는 ServiceAccount 토큰으로, 밖에서는 kubeconfig로 인증한다 —
 * fabric8이 순서대로 찾는다. 어느 쪽도 없으면 클라이언트 생성은 성공하고 첫 호출에서
 * 실패하는데, 그 실패가 503으로 나가는 것이 의도한 동작이다.
 *
 * <p>deepmesh.kubernetes.enabled=false면 연동을 끄고 토폴로지만 503으로 떨어뜨린다.
 * 나머지 엔드포인트(events·stats)는 K8s와 무관하게 그대로 동작한다.
 *
 * <p>여기서 @ConditionalOnMissingBean은 쓰지 않는다. 일반 @Configuration에서는 평가
 * 순서가 보장되지 않아, 테스트가 대역을 등록해도 이쪽 빈이 함께 살아 중복이 된다.
 * 대역을 끼우는 쪽이 @Primary로 이긴다.
 */
@Configuration
@Slf4j
public class KubernetesConfig {

	@Bean(destroyMethod = "close")
	@ConditionalOnProperty(name = "deepmesh.kubernetes.enabled", havingValue = "true", matchIfMissing = true)
	public KubernetesClient kubernetesClient() {
		return new KubernetesClientBuilder().build();
	}

	@Bean
	@ConditionalOnProperty(name = "deepmesh.kubernetes.enabled", havingValue = "true", matchIfMissing = true)
	public ClusterTopologySource clusterTopologySource(
			KubernetesClient client,
			@Value("${deepmesh.control-plane.host:}") String controlPlaneHost,
			@Value("${deepmesh.topology.gateway:frontend}") String[] gatewayNodes) {
		log.info("K8s 연동 활성 — master={}, control-plane={}, gateway={}",
				client.getMasterUrl(), controlPlaneHost.isBlank() ? "(미지정)" : controlPlaneHost,
				Arrays.toString(gatewayNodes));
		return new Fabric8ClusterTopologySource(client, controlPlaneHost, Set.of(gatewayNodes));
	}

	@Bean
	@ConditionalOnProperty(name = "deepmesh.kubernetes.enabled", havingValue = "false")
	public ClusterTopologySource disabledClusterTopologySource() {
		log.info("K8s 연동 비활성 — 토폴로지 엔드포인트는 503을 돌려준다");
		return new UnavailableClusterTopologySource();
	}
}
