FROM ubuntu:22.04

ARG DEBIAN_FRONTEND=noninteractive
ARG DOCKER_USERS=cdky
ARG USER_ID=1000
ARG GROUP_ID=1000

ENV TZ=Asia/Shanghai     LANG=C.UTF-8     LC_ALL=C.UTF-8     PYTHONDONTWRITEBYTECODE=1     PYTHONUNBUFFERED=1     PIP_NO_CACHE_DIR=1     VIRTUAL_ENV=/opt/venv     PATH=/opt/venv/bin:$PATH

RUN sed -i 's|http://archive.ubuntu.com/ubuntu|http://mirrors.aliyun.com/ubuntu|g; s|http://security.ubuntu.com/ubuntu|http://mirrors.aliyun.com/ubuntu|g' /etc/apt/sources.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        bash \
        build-essential \
        ca-certificates \
        curl \
        git \
        iproute2 \
        iputils-ping \
        less \
        locales \
        nano \
        net-tools \
        procps \
        python3 \
        python3-pip \
        python3-venv \
        sudo \
        tzdata \
        vim \
    && locale-gen C.UTF-8 \
    && python3 -m venv /opt/venv \
    && /opt/venv/bin/pip install --upgrade pip \
    && groupadd --gid "${GROUP_ID}" "${DOCKER_USERS}" \
    && useradd --uid "${USER_ID}" --gid "${GROUP_ID}" --create-home --shell /bin/bash "${DOCKER_USERS}" \
    && usermod -aG sudo "${DOCKER_USERS}" \
    && echo "%sudo ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/nopasswd \
    && chmod 0440 /etc/sudoers.d/nopasswd \
    && mkdir -p /app \
    && chown -R "${USER_ID}:${GROUP_ID}" /app "/home/${DOCKER_USERS}" \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt /tmp/requirements.txt

RUN /opt/venv/bin/pip install -r /tmp/requirements.txt     && rm -f /tmp/requirements.txt

USER ${DOCKER_USERS}

EXPOSE 8501

CMD ["python", "-m", "streamlit", "run", "app.py", "--server.address=0.0.0.0", "--server.port=8501"]
