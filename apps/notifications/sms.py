"""SMS delivery behind a small interface so a gateway (Beem, NextSMS, ...) can be
plugged in later by writing one backend class and setting SMS_BACKEND."""

import logging

from django.conf import settings
from django.utils.module_loading import import_string

logger = logging.getLogger(__name__)


class BaseSMSBackend:
    def send(self, to: str, body: str) -> None:
        raise NotImplementedError


class ConsoleSMSBackend(BaseSMSBackend):
    """Development backend: writes messages to the log instead of sending them."""

    def send(self, to: str, body: str) -> None:
        logger.info("SMS to %s: %s", to, body)


class DisabledSMSBackend(BaseSMSBackend):
    def send(self, to: str, body: str) -> None:
        pass


def get_backend() -> BaseSMSBackend:
    return import_string(settings.SMS_BACKEND)()


def send_sms(to: str, body: str) -> None:
    get_backend().send(to, body)
