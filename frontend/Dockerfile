# ---- build (Vite) ----
FROM node:26.12.0-alpine@sha256:6f08a523443ddedf52941874c203475b0ad503e859ad70cb26ab8be9a517dbd5 AS build

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
