FROM maven:3.9.9-eclipse-temurin-21 AS build
WORKDIR /build
COPY pom.xml .
COPY src src
RUN --mount=type=cache,target=/root/.m2 MAVEN_OPTS="-Xmx256m" mvn -B -ntp verify

FROM eclipse-temurin:21-jre-jammy
WORKDIR /app
COPY --from=build /build/target/husky-validator-1.0.0.jar /app/service.jar
COPY --from=build /build/target/lib /app/lib
COPY --from=build /build/target/schema /app/schema
USER 10001:10001
EXPOSE 8091
ENTRYPOINT ["java", "-Xmx1536m", "-XX:+ExitOnOutOfMemoryError", "-Dsun.net.httpserver.maxConnections=32", "-Dsun.net.httpserver.maxReqTime=30", "-Dsun.net.httpserver.maxRspTime=120", "-Djavax.xml.accessExternalDTD=", "-Djavax.xml.accessExternalSchema=", "-Djavax.xml.accessExternalStylesheet=", "-cp", "/app/service.jar:/app/lib/*", "ch.omnilink.validation.ValidationServer"]
