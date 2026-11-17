# syntax=docker/dockerfile:1.7
# Dry-run gateway (deploy tasks 3 to 5): the real Caddy config with a static placeholder page and
# no frontend build. The /api routes answer 503 (UPSTREAM_UNAVAILABLE) because no Brain runs.
ARG CADDY_IMAGE=caddy:2.11.9-alpine@sha256:003a97808e781aa9f7e75cc2f43d34d461099031faf5e20faefb9f61126836f0
FROM ${CADDY_IMAGE}
RUN install -m 0755 /usr/bin/caddy /usr/local/bin/caddy && rm /usr/bin/caddy \
 && addgroup -g 10001 -S app && adduser -u 10001 -G app -S -H -D app \
 && mkdir -p /data/caddy /config/caddy && chown -R 10001:10001 /data /config
COPY deploy/caddy/Caddyfile deploy/caddy/Caddyfile.prod /etc/caddy/
COPY deploy/caddy/snippets/common.caddy /etc/caddy/snippets/common.caddy
COPY deploy/placeholder/index.html /srv/index.html
RUN printf '%s\n' "header Content-Security-Policy \"default-src 'self'; style-src 'self' 'unsafe-inline'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'\"" \
      > /etc/caddy/snippets/csp.caddy \
 && cp /srv/index.html /srv/404.html
ENV XDG_DATA_HOME=/data XDG_CONFIG_HOME=/config
USER 10001:10001
EXPOSE 8080
CMD ["caddy", "run", "--config", "/etc/caddy/Caddyfile", "--adapter", "caddyfile"]
