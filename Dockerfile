FROM ubuntu:22.04

WORKDIR /opend

RUN apt-get update && \
    apt-get install -y curl ca-certificates tar && \
    rm -rf /var/lib/apt/lists/*

RUN curl -fL -o /tmp/opend.tar.gz \
    https://softwaredownload.futustatic.com/moomoo_OpenD_10.11.7108_Ubuntu18.04.tar.gz && \
    tar -xzf /tmp/opend.tar.gz -C /tmp && \
    cp -a /tmp/moomoo_OpenD_10.11.7108_Ubuntu18.04/moomoo_OpenD_10.11.7108_Ubuntu18.04/. /opend/ && \
    rm -rf /tmp/opend.tar.gz /tmp/moomoo_OpenD_10.11.7108_Ubuntu18.04

COPY entrypoint.sh /entrypoint.sh

RUN chmod +x /entrypoint.sh /opend/OpenD

EXPOSE 11111

ENTRYPOINT ["/entrypoint.sh"]
