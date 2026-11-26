FROM maven:3.9-eclipse-temurin-17 AS build
WORKDIR /workspace
COPY pom.xml .
COPY src ./src
RUN mvn --batch-mode --no-transfer-progress -DskipTests package

FROM hapiproject/hapi@sha256:d7f38d3676900b07e8a7d3500426eaf8d90ea9ced9a6726416f080f68e230fb0
COPY --from=build --chown=65532:65532 \
    /workspace/target/hapi-mdm-projection-extension-0.1.0-SNAPSHOT.jar \
    /app/extra-classes/hapi-mdm-projection-extension.jar
USER 65532:65532
