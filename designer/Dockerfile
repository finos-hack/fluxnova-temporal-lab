# Build context: repository root (see docker-compose.yml)

## 1. Fetch the Fluxnova-flavoured modeler build (same library as Fluxnova Modeler)
##    and build the Temporal task plugin.
FROM node:22-alpine AS build
WORKDIR /build
RUN apk add --no-cache zip \
 && npm init -y >/dev/null \
 && npm install --no-audit --no-fund camunda-bpmn-js@5
COPY plugin ./plugin
RUN node --test plugin/test/*.test.js \
 && node plugin/build.mjs \
 && cd plugin/dist && zip -qr /build/fluxnova-temporal-task-plugin.zip fluxnova-temporal-task

## 2. Serve the designer.
FROM nginx:1.29-alpine
COPY designer/nginx.conf /etc/nginx/conf.d/default.conf
COPY designer/public /usr/share/nginx/html
COPY --from=build /build/node_modules/camunda-bpmn-js/dist /usr/share/nginx/html/vendor/camunda-bpmn-js
COPY --from=build /build/plugin/dist /usr/share/nginx/html/plugin
COPY --from=build /build/fluxnova-temporal-task-plugin.zip /usr/share/nginx/html/downloads/fluxnova-temporal-task-plugin.zip
COPY fluxnova/src/main/resources/processes /usr/share/nginx/html/diagrams
EXPOSE 80
