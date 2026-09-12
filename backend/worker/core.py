"""The replaceable workload. No network access or AWS coupling."""

from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO
import qrcode


@dataclass(frozen=True)
class Artifact:
    content: bytes
    checksum: str
    media_type: str = "image/png"


def render_qr(payload: str) -> Artifact:
    if not isinstance(payload, str) or not payload.strip():
        raise ValueError("Enter some text or a URL.")
    if len(payload.encode("utf-8")) > 512:
        raise ValueError("Payload exceeds 512 UTF-8 bytes.")
    code = qrcode.QRCode(
        error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=7, border=4
    )
    code.add_data(payload)
    code.make(fit=True)
    buffer = BytesIO()
    code.make_image(fill_color="#0b1720", back_color="white").save(buffer, format="PNG")
    content = buffer.getvalue()
    return Artifact(content, sha256(content).hexdigest())
