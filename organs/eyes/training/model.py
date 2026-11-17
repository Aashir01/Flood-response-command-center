"""Model with the preprocessing inside (design 3.1): raw sigma0 dB (VV, VH) in, water logit out.

``RawDbUnet`` clips each band to [-35, +5] dB, builds (VV, VH, VV-VH), normalizes with the
train-split constants and runs a U-Net/ResNet-18 with a light decoder. The same module is used
for training and for the ONNX export, so preprocessing cannot drift between the two.
"""

from __future__ import annotations

from typing import Any

import segmentation_models_pytorch as smp
import torch
from torch import nn

QUANT_LO = -35.0
QUANT_HI = 5.0


class RawDbUnet(nn.Module):  # type: ignore[misc]
    def __init__(
        self,
        mean: list[float],
        std: list[float],
        encoder: str = "resnet18",
        encoder_weights: str | None = "imagenet",
        decoder_channels: tuple[int, ...] = (128, 64, 32, 16, 16),
    ) -> None:
        super().__init__()
        self.net = smp.Unet(
            encoder,
            encoder_weights=encoder_weights,
            in_channels=3,
            classes=1,
            decoder_channels=decoder_channels,
        )
        self.register_buffer("mean", torch.tensor(mean, dtype=torch.float32).view(1, 3, 1, 1))
        self.register_buffer("std", torch.tensor(std, dtype=torch.float32).view(1, 3, 1, 1))

    def forward(self, db: torch.Tensor) -> torch.Tensor:
        x = torch.clamp(db, QUANT_LO, QUANT_HI)
        vv = x[:, 0:1]
        vh = x[:, 1:2]
        ch = torch.cat([vv, vh, vv - vh], dim=1)
        ch = (ch - self.mean) / self.std
        out: torch.Tensor = self.net(ch)
        return out


def build(cfg: dict[str, Any], mean: list[float], std: list[float], pretrained: bool) -> RawDbUnet:
    m = cfg["model"]
    return RawDbUnet(
        mean,
        std,
        encoder=m["encoder"],
        encoder_weights=m["encoder_weights"] if pretrained else None,
        decoder_channels=tuple(m["decoder_channels"]),
    )
