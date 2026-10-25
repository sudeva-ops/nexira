FROM node:24-alpine AS build
WORKDIR /src
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
ARG VITE_HOME_TZ=Asia/Dubai
ARG VITE_DEMO_MODE=false
ARG VITE_OIDC_URL=http://localhost:8080
ARG VITE_OIDC_REALM=nexira-demo
ARG VITE_OIDC_CLIENT_ID=nexira-web
ENV VITE_HOME_TZ=$VITE_HOME_TZ VITE_DEMO_MODE=$VITE_DEMO_MODE \
    VITE_OIDC_URL=$VITE_OIDC_URL VITE_OIDC_REALM=$VITE_OIDC_REALM VITE_OIDC_CLIENT_ID=$VITE_OIDC_CLIENT_ID
RUN npm run build

# Unprivileged nginx (port 8080, any UID in group 0): runs under the restricted
# Pod Security Standard and OpenShift's restricted SCC (Prompt 16).
FROM nginxinc/nginx-unprivileged:1.27-alpine
ARG VITE_OIDC_URL=http://localhost:8080
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY security-headers.conf.template /tmp/security-headers.conf.template
USER root
# The IdP's origin (scheme://host[:port]) goes into the CSP, at build time, so the
# configuration stays read-only at run time.
RUN mkdir -p /etc/nginx/snippets \
 && NEXIRA_OIDC_ORIGIN="$(echo "$VITE_OIDC_URL" | sed -E 's#^(https?://[^/]+).*#\1#')" \
    envsubst '${NEXIRA_OIDC_ORIGIN}' < /tmp/security-headers.conf.template \
    > /etc/nginx/snippets/security-headers.conf \
 && rm /tmp/security-headers.conf.template
USER 101
COPY --from=build /src/dist /usr/share/nginx/html
EXPOSE 8080
