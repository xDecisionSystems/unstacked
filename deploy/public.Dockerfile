# syntax=docker/dockerfile:1

# Bakes the public site's nginx config into the image rather than bind-mounting
# it from the host at container start. A host bind-mount depends on the
# deployment platform's checkout/sync of this repo actually containing the
# file at the exact path docker-compose.yaml names -- if that sync is stale or
# incomplete (e.g. a persistent deploy directory that predates this file being
# added), Docker silently creates an empty directory at the missing path and
# then fails to bind it onto /etc/nginx/conf.d/default.conf, which is a file
# in the base image. Baking it into the image at build time removes that
# whole failure class: the config ships with the image, the same way the
# `app` image already ships its own source rather than mounting it.
FROM nginx:1.27-alpine
COPY deploy/public-nginx.conf /etc/nginx/conf.d/default.conf
# Outside conf.d/ deliberately: nginx.conf's `include conf.d/*.conf` would
# otherwise also try to load this snippet directly as its own top-level
# server config, which it is not.
COPY deploy/public-security-headers.conf /etc/nginx/public-security-headers.conf
# The public-site volume is shared with the app container, and Docker seeds a
# fresh named volume from whichever container mounts it first. nginx's default
# html (root-owned) would otherwise win and leave the app -- which runs as
# UID 999 -- unable to write builds. An empty directory owned by that UID
# seeds the volume correctly regardless of start order.
RUN rm -rf /usr/share/nginx/html \
    && mkdir /usr/share/nginx/html \
    && chown 999:999 /usr/share/nginx/html
