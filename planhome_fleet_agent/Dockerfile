ARG BUILD_ARCH
ARG BUILD_VERSION

FROM ghcr.io/home-assistant/${BUILD_ARCH}-base-python:3.13-alpine3.21

ARG BUILD_ARCH
ARG BUILD_VERSION

LABEL io.hass.version="${BUILD_VERSION}" \
      io.hass.type="app" \
      io.hass.arch="${BUILD_ARCH}" \
      io.hass.name="Plan@Home Fleet Agent" \
      io.hass.description="Secure outbound monitoring agent for Plan@Home Fleetmanager"

RUN pip3 install --no-cache-dir requests==2.32.5

COPY rootfs /

RUN chmod a+x /etc/services.d/fleet-agent/run
