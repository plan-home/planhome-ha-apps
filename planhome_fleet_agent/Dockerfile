ARG BUILD_FROM
FROM $BUILD_FROM
RUN pip3 install --no-cache-dir requests==2.32.5
COPY rootfs /
RUN chmod a+x /etc/services.d/fleet-agent/run
