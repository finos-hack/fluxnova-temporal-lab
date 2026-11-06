## Build stage
FROM maven:3.9-eclipse-temurin-21 AS builder
WORKDIR /workspace
COPY fluxnova/pom.xml ./pom.xml
RUN mvn -q -B dependency:go-offline
COPY fluxnova/src ./src
RUN mvn -q -B package -DskipTests

## Runtime stage
FROM eclipse-temurin:21-jre-alpine
WORKDIR /app
RUN addgroup -S fluxnova && adduser -S fluxnova -G fluxnova
USER fluxnova
COPY --from=builder /workspace/target/fluxnova-engine.jar app.jar
EXPOSE 8080
HEALTHCHECK --interval=10s --timeout=5s --start-period=90s --retries=12 \
  CMD wget -q --spider http://localhost:8080/actuator/health || exit 1
ENTRYPOINT ["java", "-jar", "app.jar"]
