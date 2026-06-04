package com.deepmesh.post.config;

import org.springframework.beans.factory.annotation.Value;
import org.apache.hc.client5.http.ConnectionKeepAliveStrategy;
import org.apache.hc.client5.http.config.ConnectionConfig;
import org.apache.hc.client5.http.config.RequestConfig;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.apache.hc.client5.http.impl.classic.HttpClientBuilder;
import org.apache.hc.client5.http.impl.classic.HttpClients;
import org.apache.hc.client5.http.impl.io.PoolingHttpClientConnectionManager;
import org.apache.hc.core5.http.Header;
import org.apache.hc.core5.util.TimeValue;
import org.apache.hc.core5.util.Timeout;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.client.ClientHttpRequestFactory;
import org.springframework.http.client.HttpComponentsClientHttpRequestFactory;
import org.springframework.web.client.RestTemplate;

@Configuration
public class RestTemplateConfig {

    // http-pool=true: Apache HttpClient 커넥션 풀 사용
    // keep-alive 여부는 내부에서 @Value로 분기
    @Bean
    @ConditionalOnProperty(name = "experiment.http-pool.enabled", havingValue = "true", matchIfMissing = true)
    public ClientHttpRequestFactory pooledFactory(
            @Value("${experiment.keep-alive.enabled:true}") boolean keepAliveEnabled) {

        PoolingHttpClientConnectionManager cm = new PoolingHttpClientConnectionManager();
        cm.setMaxTotal(100);
        cm.setDefaultMaxPerRoute(20);
        cm.setDefaultConnectionConfig(
                ConnectionConfig.custom()
                        .setConnectTimeout(Timeout.ofMilliseconds(3_000))
                        .setSocketTimeout(Timeout.ofMilliseconds(5_000))
                        .setTimeToLive(TimeValue.ofMinutes(5))
                        .build()
        );

        RequestConfig requestConfig = RequestConfig.custom()
                .setConnectionRequestTimeout(Timeout.ofMilliseconds(1_000))
                .build();

        HttpClientBuilder builder = HttpClients.custom()
                .setConnectionManager(cm)
                .setDefaultRequestConfig(requestConfig)
                .evictExpiredConnections();

        if (keepAliveEnabled) {
            // Keep-Alive 응답 헤더 파싱 후 서버 지정 timeout 적용, 없으면 60s
            ConnectionKeepAliveStrategy strategy = (response, context) -> {
                Header header = response.getFirstHeader("Keep-Alive");
                if (header != null) {
                    for (String part : header.getValue().split(",")) {
                        String[] kv = part.trim().split("=", 2);
                        if (kv.length == 2 && "timeout".equalsIgnoreCase(kv[0].trim())) {
                            try {
                                return TimeValue.ofSeconds(Long.parseLong(kv[1].trim()));
                            } catch (NumberFormatException ignored) {
                            }
                        }
                    }
                }
                return TimeValue.ofSeconds(60);
            };
            builder.setKeepAliveStrategy(strategy)
                    .evictIdleConnections(TimeValue.ofSeconds(55));
        } else {
            // 커넥션을 풀에 반납하지 않고 즉시 닫음 → keep-alive 비활성 효과
            builder.setConnectionReuseStrategy((request, response, context) -> false);
        }

        return new HttpComponentsClientHttpRequestFactory(builder.build());
    }

    // http-pool=false: 매 요청마다 새 TCP 연결 (keep-alive 클라이언트 측 N/A)
    @Bean
    @ConditionalOnProperty(name = "experiment.http-pool.enabled", havingValue = "false")
    public ClientHttpRequestFactory simpleFactory() {
        return new SimpleClientHttpRequestFactory();
    }

    // RestTemplate 빈은 항상 생성, factory만 교체됨
    @Bean
    public RestTemplate restTemplate(ClientHttpRequestFactory factory) {
        return new RestTemplate(factory);
    }
}