FROM --platform=linux/amd64 metabase/metabase:latest

COPY docker-entrypoint.sh /app/

RUN ["chmod", "+x", "/app/docker-entrypoint.sh"]

ENTRYPOINT [ "/app/docker-entrypoint.sh" ]
