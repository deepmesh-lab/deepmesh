# 빌드 단계 — 소스에서 bootJar를 만든다.
FROM eclipse-temurin:17-jdk AS build
WORKDIR /src

# 의존성 레이어를 먼저 굳힌다. src만 바뀐 재빌드에서 이 레이어가 캐시된다.
COPY gradle gradle
COPY gradlew settings.gradle build.gradle gradle.properties ./
RUN ./gradlew --no-daemon dependencies > /dev/null 2>&1 || true

COPY src src
# 테스트는 CI에서 돈다. 이미지 빌드가 H2·컨텍스트 기동까지 떠안을 이유가 없다.
RUN ./gradlew --no-daemon bootJar -x test

# 실행 단계 — JRE만 남긴다.
FROM eclipse-temurin:17-jre
WORKDIR /app

# 로그·에러 메시지가 한국어라 인코딩을 고정한다. 미지정 시 컨테이너 기본 로캘(POSIX)로
# 떨어져 깨진다.
ENV LANG=C.UTF-8
ENV JAVA_TOOL_OPTIONS="-Dfile.encoding=UTF-8"

COPY --from=build /src/build/libs/*.jar app.jar

EXPOSE 8080

# K8s 안에서는 ServiceAccount 토큰으로 K8s API에 붙는다(토폴로지). 밖에서 띄우려면
# deepmesh.kubernetes.enabled=false로 두면 토폴로지만 503이 되고 나머지는 동작한다.
ENTRYPOINT ["java", "-jar", "/app.jar"]
