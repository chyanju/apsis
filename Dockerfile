# Apsis with the environments of the benchmark suite and the .NET front-end, set up to run offline.
#   docker build -t apsis .
#   docker run --rm -it --network none apsis

FROM rust:1.97.1-slim-bookworm@sha256:2775a09d208ff0d7c1f50490c45b62db929e87ba1dcbc3f2132ac71a704bcdd3 AS build
WORKDIR /src
COPY Cargo.toml Cargo.lock ./
COPY crates crates
COPY examples examples
RUN cargo build --release --locked && cargo test --release --locked

FROM mcr.microsoft.com/dotnet/sdk:10.0.404-noble@sha256:bef136a371963aaa46ec97882845ef6f54dec15728bb4b128b1c2a400ffbc9b4
ENV DEBIAN_FRONTEND=noninteractive \
    DOTNET_CLI_TELEMETRY_OPTOUT=1 \
    DOTNET_NOLOGO=1 \
    DOTNET_SKIP_FIRST_TIME_EXPERIENCE=1 \
    NUGET_PACKAGES=/opt/nuget \
    UV_PYTHON_INSTALL_DIR=/opt/python \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1

# Python 3.12 from Ubuntu for two environments, 3.13.9 through uv for the others (precompiled: the front-ends write no bytecode)
RUN apt-get update \
 && apt-get install -y --no-install-recommends python3 python3-venv \
 && rm -rf /var/lib/apt/lists/*
RUN python3 -m venv /opt/uv \
 && echo "uv==0.13.8 --hash=sha256:5337c30bb893b4f9ce0ceb921ba2da0d13f649da644f40ad3bef84083bef0203 --hash=sha256:e18a57b8b352eb7c8feb317b9f6f533c8f0ad9673fd6cf34bbe3cf1a9f6a8984" > /tmp/uv.txt \
 && /opt/uv/bin/pip install --quiet --require-hashes --only-binary=:all: -r /tmp/uv.txt \
 && rm /tmp/uv.txt \
 && /opt/uv/bin/uv python install --compile-bytecode 3.13.9

WORKDIR /apsis
COPY . .
COPY --from=build /src/target/release/apsis target/release/apsis
RUN python3 scripts/setup_envs.py --python "$(/opt/uv/bin/uv python find 3.13.9)" --with-frontends
# Langflow and Flowise flows need only their front-ends, which the image's python3 imports
RUN site="$(python3 -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')" \
 && mkdir -p "$site" \
 && printf '%s\n' /apsis/frontends/common /apsis/frontends/langflow /apsis/frontends/flowise > "$site/apsis-frontends.pth"
# the packages of the .NET front-end's tests, so that they run offline
RUN dotnet restore frontends/agent-framework-dotnet/tests
ENV PATH=/apsis/target/release:/apsis/.envs/dotnet/frontend:$PATH
CMD ["bash"]
