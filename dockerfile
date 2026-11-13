FROM alpine:3.20

RUN apk add --no-cache bash socat jq yq curl ca-certificates && \
    adduser -D -u 10001 appuser

WORKDIR /app
COPY rules.yaml /app/rules.yaml
COPY schema/rules.schema.json /app/schema/rules.schema.json
COPY server.sh /app/server.sh

RUN chown -R 10001:10001 /app && chmod +x /app/server.sh

USER 10001
EXPOSE 8000

ENTRYPOINT ["/app/server.sh"]
