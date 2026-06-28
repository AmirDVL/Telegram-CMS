"""Structured JSON logging (structlog), shared across services."""

from __future__ import annotations

import logging
import sys

import structlog


def configure_logging(service: str, level: str = "INFO") -> None:
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, level.upper(), logging.INFO),
    )

    structlog.configure(
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level.upper(), logging.INFO)
        ),
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            _add_service(service),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def _add_service(service: str):
    def processor(logger, method_name, event_dict):
        event_dict["service"] = service
        return event_dict

    return processor


def get_logger(name: str | None = None):
    return structlog.get_logger(name)
