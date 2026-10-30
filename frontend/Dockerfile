# Development image for the board: the Vite dev server with hot reload. The
# source is bind-mounted by docker-compose.yml; node_modules stays in the image.
FROM node:22-slim

WORKDIR /app/frontend
COPY package.json package-lock.json ./
RUN npm ci
COPY . .

EXPOSE 3200
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]
