FROM node:18-slim

ENV DEBIAN_FRONTEND=noninteractive
ENV LANG=C.UTF-8

# 系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    wget \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# npm 升级
RUN npm install -g npm@latest

WORKDIR /workspace