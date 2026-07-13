from dataclasses import dataclass
from types import ModuleType

from app.parsers import generic, p104, p1111
from app.parsers.common import extract_fields


@dataclass(frozen=True)
class AdapterOutput:
    platform: str
    version: str
    layout_recognized: bool
    payload: dict
    confidence: dict[str, float]


PLATFORM_MODULES: dict[str, ModuleType] = {"p104": p104, "p1111": p1111}


def _detected_platform(text: str) -> str | None:
    lowered = text.lower()
    for platform, module in PLATFORM_MODULES.items():
        if any(signature.lower() in lowered for signature in module.SIGNATURES):
            return platform
    return None


def select_adapter(text: str, requested_platform: str = "generic") -> AdapterOutput:
    detected = _detected_platform(text)
    platform = detected or requested_platform
    if platform not in {"p104", "p1111", "direct", "generic"}:
        platform = "generic"
    module = PLATFORM_MODULES.get(platform, generic)
    payload, confidence = extract_fields(text, module.RULES)

    # A claimed job-board export without its stable brand marker is an unknown
    # layout.  Never silently treat it as calibrated, even if generic fields parse.
    if platform in PLATFORM_MODULES:
        recognized = detected == platform
    else:
        recognized = bool(payload["name"] and (payload["email"] or payload["phone"]))
    return AdapterOutput(
        platform=platform,
        version=module.VERSION,
        layout_recognized=recognized,
        payload=payload,
        confidence=confidence,
    )
