"""외부 통신 차단.

프로그램 시작 시 인터넷 소켓 연결을 막아, 라이브러리가 몰래 통신하려 해도
실패하게 만든다. 업무망 연결 자체는 PC 보안 체계가 관리하고, 이 프로그램은
스스로 어떤 외부 통신도 하지 않음을 보장하는 용도다.
"""

from __future__ import annotations

import socket

_INET = (socket.AF_INET, socket.AF_INET6)
_blocked = False


class NetworkBlockedError(OSError):
    pass


def _refuse(*_args, **_kwargs):
    raise NetworkBlockedError("이 프로그램은 외부 통신을 하지 않도록 차단되어 있습니다.")


def block_network() -> None:
    global _blocked
    if _blocked:
        return
    orig_connect, orig_connect_ex = socket.socket.connect, socket.socket.connect_ex

    def connect(self, address):
        if self.family in _INET:
            _refuse()
        return orig_connect(self, address)

    def connect_ex(self, address):
        if self.family in _INET:
            _refuse()
        return orig_connect_ex(self, address)

    socket.socket.connect = connect
    socket.socket.connect_ex = connect_ex
    socket.create_connection = _refuse
    socket.getaddrinfo = _refuse
    _blocked = True


def is_blocked() -> bool:
    return _blocked
