from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol


class ScanStatus(StrEnum):
    CLEAN = "clean"
    INFECTED = "infected"
    UNAVAILABLE = "unavailable"
    ERROR = "error"


@dataclass(frozen=True)
class ScanResult:
    status: ScanStatus
    detail: str | None = None


class FileScanner(Protocol):
    def scan(self, path: Path) -> ScanResult: ...


class UnavailableScanner:
    """Explicit development-only scanner; policy decides whether upload may continue."""

    def scan(self, path: Path) -> ScanResult:
        return ScanResult(ScanStatus.UNAVAILABLE, "Malware scanner is disabled")


class ClamAVScanner:
    def __init__(self, host: str, port: int, timeout: float = 10.0) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout

    def scan(self, path: Path) -> ScanResult:
        try:
            import clamd

            client = clamd.ClamdNetworkSocket(
                host=self.host,
                port=self.port,
                timeout=self.timeout,
            )
            client.ping()
            with path.open("rb") as stream:
                response = client.instream(stream)
            if not response:
                return ScanResult(ScanStatus.ERROR, "ClamAV returned no result")
            status, signature = next(iter(response.values()))
            if status == "OK":
                return ScanResult(ScanStatus.CLEAN)
            if status == "FOUND":
                return ScanResult(ScanStatus.INFECTED, str(signature or "malware detected"))
            return ScanResult(ScanStatus.ERROR, f"Unexpected ClamAV status: {status}")
        except (ConnectionError, OSError) as exc:
            return ScanResult(ScanStatus.UNAVAILABLE, str(exc))
        except Exception as exc:
            return ScanResult(ScanStatus.ERROR, str(exc))
