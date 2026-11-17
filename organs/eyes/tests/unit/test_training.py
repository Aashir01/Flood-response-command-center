"""Training data and loss (tasks 1 and 2): crops, augmentation, ignore index, one step.

The data tests need only NumPy. The loss and training-step tests need the ``train`` extra
(``torch``, ``segmentation_models_pytorch``) and are skipped without it, so the runtime image
and the default CI job do not install PyTorch.
"""

from __future__ import annotations

import sys
from typing import Any

import numpy as np
import pytest

from stitch_eyes.settings import ORGAN_DIR

sys.path.insert(0, str(ORGAN_DIR / "training"))

from data import Chip, augment, channel_stats, epoch_samples, random_crop

AUG = {"bias_db": 1.5, "noise_db": 0.5, "flips": True, "rot90": True, "quantize": True}


def _chip(seed: int, size: int = 64, ignore_top: int = 0) -> Chip:
    rng = np.random.default_rng(seed)
    label = (rng.random((size, size)) < 0.3).astype(np.int16)
    label[:ignore_top] = -1
    s1 = np.where(label == 1, -20.0, -9.0)[None].repeat(2, axis=0).astype(np.float32)
    s1 += rng.normal(0, 1.0, s1.shape).astype(np.float32)
    return Chip(f"c{seed}", s1, label)


def test_samples_have_the_crop_shape_and_dtypes() -> None:
    rng = np.random.default_rng(0)
    samples = epoch_samples(rng, [_chip(0), _chip(1)], 32, 3, AUG)
    assert len(samples) == 6
    for x, y in samples:
        assert x.shape == (2, 32, 32) and x.dtype == np.float32
        assert y.shape == (32, 32) and y.dtype == np.int16
        assert set(np.unique(y)) <= {-1, 0, 1}


def test_crops_never_contain_only_ignored_pixels() -> None:
    rng = np.random.default_rng(1)
    chip = _chip(2, size=64, ignore_top=56)  # only 8 labelled rows
    for _ in range(200):
        got = random_crop(rng, chip, 32)
        if got is not None:
            assert np.any(got[1] != -1)
    all_ignored = Chip("x", chip.s1, np.full((64, 64), -1, np.int16))
    assert random_crop(rng, all_ignored, 32) is None


def test_augmentation_moves_labels_with_pixels() -> None:
    """Flips and rotations act on image and label together: water stays where it is dark."""
    rng = np.random.default_rng(3)
    chip = _chip(4)
    noise_free = {**AUG, "bias_db": 0.0, "noise_db": 0.0, "quantize": False}
    for _ in range(20):
        x, y = augment(rng, chip.s1, chip.label, **noise_free)  # type: ignore[arg-type]
        water = y == 1
        assert x[1][water].mean() < x[1][~water].mean() - 5.0


def test_epoch_samples_are_deterministic_for_a_seed() -> None:
    chips = [_chip(5), _chip(6)]
    a = epoch_samples(np.random.default_rng(9), chips, 32, 2, AUG)
    b = epoch_samples(np.random.default_rng(9), chips, 32, 2, AUG)
    assert all(
        np.array_equal(p[0], q[0]) and np.array_equal(p[1], q[1]) for p, q in zip(a, b, strict=True)
    )


def test_channel_stats_ignore_unlabelled_pixels() -> None:
    chip = _chip(7, ignore_top=32)
    poisoned = chip.s1.copy()
    poisoned[:, :32] = 4.0  # only under label -1
    m1, s1 = channel_stats([chip])
    m2, s2 = channel_stats([Chip("p", poisoned, chip.label)])
    assert np.allclose(m1, m2) and np.allclose(s1, s2)


def _train_mod() -> Any:
    pytest.importorskip("torch")
    pytest.importorskip("segmentation_models_pytorch")
    import train

    return train


def test_loss_ignores_label_minus_one() -> None:
    train = _train_mod()
    import torch

    g = torch.Generator().manual_seed(0)
    z = torch.randn(2, 1, 16, 16, generator=g)
    y = (torch.rand(2, 1, 16, 16, generator=g) > 0.5).long()
    y[:, :, :8] = -1
    base = train.masked_loss(z, y, 1.0, 1.0)
    z2 = z.clone()
    z2[:, :, :8] = 50.0  # change logits only where the label is ignored
    assert torch.allclose(base, train.masked_loss(z2, y, 1.0, 1.0))


def test_one_training_step_lowers_the_loss() -> None:
    train = _train_mod()
    import torch
    import yaml
    from model import build

    cfg = yaml.safe_load((ORGAN_DIR / "training" / "config.yaml").read_text())
    train.seed_all(0)
    torch.set_num_threads(2)
    model = build(cfg, [-10.0, -17.0, 7.0], [4.0, 4.5, 3.3], pretrained=False)
    chips = [_chip(10), _chip(11)]
    samples = epoch_samples(np.random.default_rng(0), chips, 64, 2, AUG)
    x = torch.from_numpy(np.stack([s[0] for s in samples]))
    y = torch.from_numpy(np.stack([s[1] for s in samples]).astype(np.int64))[:, None]
    opt = torch.optim.AdamW(model.parameters(), lr=1e-3)
    model.train()
    losses = []
    for _ in range(4):
        loss = train.masked_loss(model(x), y, 1.0, 1.0)
        opt.zero_grad()
        loss.backward()
        opt.step()
        losses.append(float(loss.detach()))
    assert losses[-1] < losses[0]
