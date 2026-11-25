"""Fail closed on socket connections during the offline verification runs."""

import os
import socket


def _network_disabled(*args, **kwargs):
    raise RuntimeError("Real network access is disabled for offline search integrity tests")


socket.create_connection = _network_disabled
socket.socket.connect = _network_disabled
socket.socket.connect_ex = _network_disabled
os.environ["PURPOSE_LANDSCAPE_OFFLINE_GUARD"] = "active"
