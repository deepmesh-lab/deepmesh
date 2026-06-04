package com.deepmesh.post.config;

import org.apache.coyote.ProtocolHandler;
import org.apache.coyote.http11.AbstractHttp11Protocol;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.boot.web.embedded.tomcat.TomcatServletWebServerFactory;
import org.springframework.boot.web.server.WebServerFactoryCustomizer;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration
public class ServerConfig {

    // enabled=true (기본): Tomcat keep-alive ON
    @Bean
    @ConditionalOnProperty(name = "experiment.keep-alive.enabled", havingValue = "true", matchIfMissing = true)
    public WebServerFactoryCustomizer<TomcatServletWebServerFactory> tomcatKeepAliveOn() {
        return factory -> factory.addConnectorCustomizers(connector -> {
            ProtocolHandler handler = connector.getProtocolHandler();
            if (handler instanceof AbstractHttp11Protocol<?> protocol) {
                protocol.setKeepAliveTimeout(60_000);   // keep-alive 유휴 대기 (ms)
                protocol.setMaxKeepAliveRequests(200);  // 커넥션당 최대 요청 수 (-1 = 무제한)
            }
        });
    }

    // enabled=false: 첫 요청 후 즉시 연결 종료 (maxKeepAliveRequests=1)
    @Bean
    @ConditionalOnProperty(name = "experiment.keep-alive.enabled", havingValue = "false")
    public WebServerFactoryCustomizer<TomcatServletWebServerFactory> tomcatKeepAliveOff() {
        return factory -> factory.addConnectorCustomizers(connector -> {
            ProtocolHandler handler = connector.getProtocolHandler();
            if (handler instanceof AbstractHttp11Protocol<?> protocol) {
                protocol.setMaxKeepAliveRequests(1);
            }
        });
    }
}