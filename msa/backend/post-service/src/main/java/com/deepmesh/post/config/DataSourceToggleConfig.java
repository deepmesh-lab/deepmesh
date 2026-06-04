package com.deepmesh.post.config;

import com.zaxxer.hikari.HikariDataSource;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.boot.autoconfigure.jdbc.DataSourceProperties;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.jdbc.datasource.DriverManagerDataSource;

import javax.sql.DataSource;

@Configuration
@EnableConfigurationProperties(DataSourceProperties.class)
public class DataSourceToggleConfig {

    // enabled=true (기본): HikariCP 풀
    @Bean
    @ConditionalOnProperty(name = "experiment.db-pool.enabled", havingValue = "true", matchIfMissing = true)
    @ConfigurationProperties(prefix = "spring.datasource.hikari")  // pool-name, max-pool-size 등 바인딩
    public HikariDataSource hikariDataSource(DataSourceProperties properties) {
        return properties.initializeDataSourceBuilder()
                .type(HikariDataSource.class)
                .build();
    }

    // enabled=false: 풀 없는 직접 연결 (매 쿼리마다 새 커넥션)
    @Bean
    @ConditionalOnProperty(name = "experiment.db-pool.enabled", havingValue = "false")
    public DataSource driverManagerDataSource(DataSourceProperties properties) {
        return properties.initializeDataSourceBuilder()
                .type(DriverManagerDataSource.class)
                .build();
    }
}