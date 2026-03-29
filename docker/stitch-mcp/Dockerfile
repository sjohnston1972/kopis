FROM node:22-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    apt-transport-https \
    ca-certificates \
    gnupg \
    && curl https://packages.cloud.google.com/apt/doc/apt-key.gpg | gpg --dearmor -o /usr/share/keyrings/cloud.google.gpg \
    && echo "deb [signed-by=/usr/share/keyrings/cloud.google.gpg] https://packages.cloud.google.com/apt cloud-sdk main" \
        > /etc/apt/sources.list.d/google-cloud-sdk.list \
    && apt-get update && apt-get install -y --no-install-recommends google-cloud-cli \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Pre-install the stitch-mcp package globally so it's cached in the image
RUN npm install -g @_davideast/stitch-mcp supergateway \
    # Patch: stitch-mcp proxy calls process.exit(0) after connect, killing the
    # stdio server before it can serve any requests. Remove that exit so the
    # Node event loop stays alive for the stdin listener.
    && sed -i 's/process.exit(0);/\/\/ process.exit(0); -- patched: keep alive for stdio/' \
       /usr/local/lib/node_modules/@_davideast/stitch-mcp/dist/commands/proxy/command.js

# Mount point for gcloud credentials persisted from host
VOLUME /root/.config/gcloud

EXPOSE 3333

# Run supergateway to bridge stitch-mcp stdio to SSE on port 3333
ENTRYPOINT ["supergateway", "--stdio", "stitch-mcp proxy", "--port", "3333"]
