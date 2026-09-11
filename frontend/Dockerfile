FROM node:24-alpine AS build

WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:1.29-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY entrypoint.sh /usr/local/bin/qa-frontend-entrypoint
RUN chmod 755 /usr/local/bin/qa-frontend-entrypoint
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
ENTRYPOINT ["/usr/local/bin/qa-frontend-entrypoint"]
CMD ["nginx", "-g", "daemon off;"]
