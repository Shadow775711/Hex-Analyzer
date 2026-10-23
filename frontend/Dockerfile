# ---- build (Vite) ----
FROM node:22.23.4-alpine@sha256:fe4f6d74e20370acb04ad889077d14d0f64a9c8ea6a42bc60cddf1e844699914 AS build

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
