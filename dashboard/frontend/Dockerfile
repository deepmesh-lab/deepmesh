FROM node:22-alpine AS build

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .

ARG VITE_DASHBOARD_API_URL
ARG VITE_USE_MOCK=false

ENV VITE_DASHBOARD_API_URL=${VITE_DASHBOARD_API_URL}
ENV VITE_USE_MOCK=${VITE_USE_MOCK}

RUN npm run build

FROM nginx:alpine

COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80
