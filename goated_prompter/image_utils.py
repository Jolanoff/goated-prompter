"""Encoded reference-image representation for multimodal backends."""

from dataclasses import dataclass


@dataclass(frozen=True)
class EncodedImage:
    data: str
    media_type: str
    width: int
    height: int

    @property
    def data_url(self):
        return f"data:{self.media_type};base64,{self.data}"
