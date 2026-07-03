# ── 빌드 스테이지 ──────────────────────
# FROM eclipse-temurin:17-jdk-alpine AS build
FROM eclipse-temurin:17-jdk AS build
WORKDIR /app

# gradlew 먼저 복사 (캐시 최적화)
COPY gradlew .
COPY gradle gradle
RUN chmod +x gradlew

# 의존성 캐시
COPY build.gradle settings.gradle ./
RUN ./gradlew dependencies --no-daemon || true

# 소스 빌드
COPY src src
RUN ./gradlew bootJar -x test --no-daemon

# ── 실행 스테이지 ──────────────────────
FROM eclipse-temurin:17-jre
WORKDIR /app
COPY --from=build /app/build/libs/*.jar app.jar
EXPOSE 8080
ENTRYPOINT ["java", "-jar", "app.jar"]