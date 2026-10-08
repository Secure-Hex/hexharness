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
        metasploit-framework \
        aircrack-ng \
        iw \
        wireless-tools \
        rfkill \
        usbutils \
        pciutils \
        minicom \
        screen \
        python3-serial \
    && rm -rf /var/lib/apt/lists/*

# metasploit-framework + aircrack-ng (wifi) + iw/wireless-tools/rfkill (wifi mgmt) +
# usbutils/pciutils (device discovery) + minicom/screen/python3-serial (USB-UART work).
# Hardware access itself is granted at `docker run` time via the engagement's
# hardware_access flag (USB passthrough + host net + privileged) — see SandboxExecutor.

WORKDIR /workspace
