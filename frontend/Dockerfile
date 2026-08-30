# syntax=docker/dockerfile:1
# Dev image — the Vite dev server with HMR. Production serves the built
# static bundle from the API container / a CDN instead.
FROM node:22-slim
WORKDIR /app

COPY package.json package-lock.json* ./
RUN npm ci || npm install

COPY . .

EXPOSE 5173
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]
