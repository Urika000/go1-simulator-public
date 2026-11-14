ARG SIM_IMAGE=go1-sim:public
FROM ${SIM_IMAGE}
USER root
COPY entrypoint.sh /entrypoint.sh
COPY example.py /opt/participant-example.py
RUN chmod +x /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]
CMD ["ping"]
