FROM ubuntu:24.04 AS input-builder
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates build-essential cmake ninja-build python3 qt6-base-dev \
    qt6-5compat-dev qt6-httpserver-dev libqca-qt6-dev libssl-dev libvncserver-dev \
    && rm -rf /var/lib/apt/lists/*
RUN apt-get update && apt-get install -y --no-install-recommends qt6-websockets-dev && rm -rf /var/lib/apt/lists/*
ADD --checksum=sha256:92ef01feb342fa1357fea5bbf957d0791d784f969ce490db2472bc59fbdb98eb https://codeload.github.com/veyon/veyon/tar.gz/refs/tags/v4.11.4 /tmp/veyon-source.tar.gz
RUN mkdir /source && tar -xzf /tmp/veyon-source.tar.gz -C /source --strip-components=1
COPY services/cmnc-veyon-service/native-input /patch
RUN python3 /patch/patch.py /source \
    && cmake -S /source -B /build -G Ninja -DWITH_CORE_ONLY=ON -DWITH_TRANSLATIONS=OFF -DWITH_LTO=OFF -DWITH_PCH=OFF -DCMAKE_BUILD_TYPE=Release \
    && cmake --build /build --target webapi --parallel 2

FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive QT_QPA_PLATFORM=offscreen XDG_RUNTIME_DIR=/tmp/veyon-runtime
ADD --checksum=sha256:c604ac465da02d116e8ed50f1dea11af65b6cd9ed7bdcbc06176ec68172e5d46 https://github.com/veyon/veyon/releases/download/v4.11.4/veyon_4.11.4.0-ubuntu.24.04_amd64.deb /tmp/veyon.deb
RUN apt-get update \
    && apt-get install -y --no-install-recommends /tmp/veyon.deb curl libqca-qt6-plugins qt6-qpa-plugins \
    && rm -f /tmp/veyon.deb \
    && rm -rf /var/lib/apt/lists/*
RUN veyon-cli config set Master/ComputerMonitoringUpdateInterval 100 \
    && veyon-cli config set WebAPI/ConnectionLimit 128 \
    && veyon-cli config set WebAPI/ConnectionIdleTimeout 60 \
    && useradd --uid 10001 --create-home veyon \
    && mkdir -p /tmp/veyon-runtime \
    && chown 10001:10001 /tmp/veyon-runtime \
    && chmod 700 /tmp/veyon-runtime
COPY --from=input-builder /build/plugins/webapi/webapi.so /usr/lib/x86_64-linux-gnu/veyon/webapi.so
USER 10001:10001
CMD ["veyon-cli", "webapi", "runserver"]
