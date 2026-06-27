from typing import Protocol


class OAuthVerifier(Protocol):
    def verify(self, id_token: str) -> dict: ...
