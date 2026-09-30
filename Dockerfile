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

# Enable OpenD internal control interface for login UI
RUN sed -i \
    's#.*<telnet_ip>127.0.0.1</telnet_ip>.*#<telnet_ip>0.0.0.0</telnet_ip>#; \
     s#.*<telnet_port>22222</telnet_port>.*#<telnet_port>22222</telnet_port>#' \
    /opend/OpenD.xml
