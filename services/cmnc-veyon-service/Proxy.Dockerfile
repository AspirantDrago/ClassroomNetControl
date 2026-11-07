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
USER 10001:10001
CMD ["veyon-cli", "webapi", "runserver"]
