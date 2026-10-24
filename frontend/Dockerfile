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

FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /src/dist /usr/share/nginx/html
EXPOSE 80
