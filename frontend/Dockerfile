# ---- build (Vite) ----
FROM node:26.13.0-alpine@sha256:8996bb5821d62a8fd9bb27c1cb07462f3fdce6e47d640c6a881ead0b064ce216 AS build

WORKDIR /app

COPY package*.json ./
# --ignore-scripts: no package install hooks (none are needed)
RUN npm ci --ignore-scripts

COPY . .
RUN npm run build

# ---- serve: rootless nginx (port 8080) ----
FROM nginxinc/nginx-unprivileged:1.31.7-alpine@sha256:b5047b9b76845eac124358373c6852377c52e4b05834a47647e955dd91cb8f1e

COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 8080
