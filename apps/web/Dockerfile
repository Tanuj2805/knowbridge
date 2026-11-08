FROM node:22-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

FROM node:22-alpine AS build
WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npm run build

FROM node:22-alpine
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 PORT=3000 HOSTNAME=0.0.0.0
RUN addgroup -S kb && adduser -S kb -G kb
COPY --from=build --chown=kb:kb /app/.next/standalone ./
COPY --from=build --chown=kb:kb /app/.next/static ./.next/static
COPY --from=build --chown=kb:kb /app/public ./public
USER kb
EXPOSE 3000
CMD ["node", "server.js"]
