FROM node:24-alpine AS build

WORKDIR /app

ARG VITE_API_BASE_URL=/api

COPY apps/cmnc-web/package*.json ./
RUN npm ci

COPY apps/cmnc-web ./
ENV VITE_API_BASE_URL=${VITE_API_BASE_URL}
RUN npm run build


FROM nginx:1.29-alpine

COPY apps/cmnc-web/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
