# syntax=docker/dockerfile:1.7
# Gateway image (deploy design 4.3): Next.js static export served by Caddy, /api proxied to the
# Brain. Same image in dev, CI and production; only the Caddyfile and published ports differ.
ARG NODE_IMAGE=node:24.22.3-alpine3.24@sha256:116b800c3754b440ee0aa3ed2f20f5bf3d99a554bfd9adeea09ea8017f6e85f5
ARG CADDY_IMAGE=caddy:2.11.9-alpine@sha256:003a97808e781aa9f7e75cc2f43d34d461099031faf5e20faefb9f61126836f0

FROM ${NODE_IMAGE} AS build
WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1 CI=1
COPY frontend/package.json frontend/package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build && test -f out/index.html
COPY deploy/bin/csp-hashes.mjs /tmp/csp-hashes.mjs
RUN node /tmp/csp-hashes.mjs out > /tmp/csp.caddy

FROM ${CADDY_IMAGE} AS runtime
# Copy the binary without its file capability (cap_net_bind_service): with cap_drop ALL and
# no-new-privileges a capability-tagged binary cannot exec. Docker already allows unprivileged
# binds to ports below 1024 (net.ipv4.ip_unprivileged_port_start=0, also set in compose.prod).
RUN install -m 0755 /usr/bin/caddy /usr/local/bin/caddy && rm /usr/bin/caddy \
 && addgroup -g 10001 -S app && adduser -u 10001 -G app -S -H -D app \
 && mkdir -p /data/caddy /config/caddy && chown -R 10001:10001 /data /config
COPY deploy/caddy/Caddyfile deploy/caddy/Caddyfile.prod /etc/caddy/
COPY deploy/caddy/snippets/common.caddy /etc/caddy/snippets/common.caddy
COPY --from=build /tmp/csp.caddy /etc/caddy/snippets/csp.caddy
COPY --from=build /app/out /srv
ENV XDG_DATA_HOME=/data XDG_CONFIG_HOME=/config
USER 10001:10001
EXPOSE 8080
CMD ["caddy", "run", "--config", "/etc/caddy/Caddyfile", "--adapter", "caddyfile"]
