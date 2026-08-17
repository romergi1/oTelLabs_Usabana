FROM public.ecr.aws/aws-observability/aws-otel-collector:v0.49.0

COPY adot-config.yaml /etc/ecs/otel-config.yaml

CMD ["--config=/etc/ecs/otel-config.yaml"]