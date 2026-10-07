# HexHarness sandbox image: Kali rolling + the tools the native tools shell out to.
# Built on demand as `hexharness/kali:latest` (SandboxExecutor auto-builds it if missing).
# Ships inside the PyPI package so the build recipe travels with HexHarness.
FROM kalilinux/kali-rolling

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
        dnsutils \
        whois \
        smbclient \
        nmap \
        netcat-traditional \
        curl \
        wget \
        openssl \
        ca-certificates \
        iputils-ping \
        net-tools \
        python3 \
        python3-pip \
        binutils \
        git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace
