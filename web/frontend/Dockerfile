# Stage 1: Build
FROM node:18-alpine AS builder

WORKDIR /app

# Аргумент для API URL (по умолчанию относительный путь для продакшена)
ARG VITE_API_URL=/api
ENV VITE_API_URL=$VITE_API_URL

# Копируем package files
COPY package*.json ./

# Устанавливаем зависимости
RUN npm ci

# Копируем исходный код
COPY . .

# Собираем приложение
RUN npm run build

# Stage 2: Production
FROM nginx:alpine

# Копируем собранное приложение
COPY --from=builder /app/dist /usr/share/nginx/html

# Копируем конфигурацию nginx
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]

