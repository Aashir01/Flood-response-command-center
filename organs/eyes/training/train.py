"""Fine-tune U-Net/ResNet-18 on the Sen1Floods11 hand-labeled train split (design 3.2, task 2).

    python organs/eyes/training/train.py --profile full   # Colab/Modal GPU (design job A)
    python organs/eyes/training/train.py --profile cpu    # reduced laptop run (shipped demo model)
    python organs/eyes/training/train.py --profile smoke  # 2 epochs on 8 chips (CPU smoke)
    ... --resume auto                                      # continue from <out>/last.pt

Model selection uses the validation split only (water-class IoU). The test split is never read
here. Writes ``<out>/best.pt``, ``<out>/last.pt`` (git-ignored), ``preprocess.json`` and a run
log ``training/runs/<profile>.json`` (small, committed).
"""

from __future__ import annotations

import argparse
import json
import math
import platform
import random
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import torch
import torch.nn.functional as F
import yaml

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from model import build  # noqa: E402

from data import channel_stats, epoch_samples, load_split  # noqa: E402

REPO = HERE.parents[2]


def seed_all(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.use_deterministic_algorithms(True, warn_only=True)


def masked_loss(
    logits: torch.Tensor, label: torch.Tensor, bce_w: float, dice_w: float
) -> torch.Tensor:
    """BCE + soft Dice on pixels with label != -1 (ignore index)."""
    keep = (label != -1).float()
    target = (label == 1).float()
    n = keep.sum().clamp_min(1.0)
    bce = (F.binary_cross_entropy_with_logits(logits, target, reduction="none") * keep).sum() / n
    p = torch.sigmoid(logits) * keep
    inter = (p * target).sum()
    dice = 1.0 - (2.0 * inter + 1.0) / (p.sum() + (target * keep).sum() + 1.0)
    return bce_w * bce + dice_w * dice


@torch.no_grad()
def evaluate(model: torch.nn.Module, chips: list[Any]) -> dict[str, float]:
    model.eval()
    tp = fp = fn = 0
    for c in chips:
        x = torch.from_numpy(np.ascontiguousarray(c.s1))[None]
        z = model(x)[0, 0].numpy()
        pred = z > 0
        lab = c.label
        keep = lab != -1
        t = lab == 1
        tp += int((pred & t & keep).sum())
        fp += int((pred & ~t & keep).sum())
        fn += int((~pred & t & keep).sum())
    model.train()
    iou = tp / max(tp + fp + fn, 1)
    f1 = 2 * tp / max(2 * tp + fp + fn, 1)
    return {"iou": iou, "f1": f1}


def lr_factor(epoch_f: float, warmup: int, total: int) -> float:
    if epoch_f < warmup:
        return (epoch_f + 1e-3) / warmup
    prog = (epoch_f - warmup) / max(total - warmup, 1)
    return 0.5 * (1 + math.cos(math.pi * min(prog, 1.0)))


def git_commit() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=REPO, check=True
        ).stdout.strip()
    except Exception:
        return "unknown"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", type=Path, default=HERE / "config.yaml")
    ap.add_argument("--profile", default="full", help="a profile name from config.yaml")
    ap.add_argument("--data-root", type=Path)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--resume", default="", help="'auto' to resume from <out>/last.pt")
    ap.add_argument("--no-pretrained", action="store_true")
    args = ap.parse_args(argv)

    cfg = yaml.safe_load(args.config.read_text())
    prof = cfg["profiles"][args.profile]
    seed = int(cfg["seed"])
    seed_all(seed)
    if prof.get("threads"):
        torch.set_num_threads(int(prof["threads"]))
    root = args.data_root or (REPO / cfg["data_root"])
    out = args.out or (REPO / cfg["out_dir"] / args.profile)
    out.mkdir(parents=True, exist_ok=True)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    amp = bool(prof.get("amp")) and device == "cuda"

    max_chips = int(prof.get("max_chips", 0))
    t_load = time.time()
    train = load_split(root, "train", max_chips)
    valid = load_split(root, "valid", max_chips)
    mean, std = channel_stats(train)
    print(f"loaded {len(train)} train / {len(valid)} valid chips in {time.time() - t_load:.0f}s")
    pre = {
        "channels": ["VV", "VH", "VV-VH"],
        "clip_db": [-35.0, 5.0],
        "mean": mean,
        "std": std,
        "input": "sigma0 dB, (1, 2, H, W) VV then VH, H and W multiples of 32",
        "computed_on": f"sen1floods11 hand-labeled train split ({len(train)} chips)",
    }
    (out / "preprocess.json").write_text(json.dumps(pre, indent=2))

    model = build(cfg, mean, std, pretrained=not args.no_pretrained).to(device)
    enc = [p for n, p in model.named_parameters() if n.startswith("net.encoder.")]
    dec = [p for n, p in model.named_parameters() if not n.startswith("net.encoder.")]
    o = cfg["optim"]
    opt = torch.optim.AdamW(
        [{"params": enc, "lr": o["lr_encoder"]}, {"params": dec, "lr": o["lr_decoder"]}],
        weight_decay=o["weight_decay"],
    )
    base_lrs = [o["lr_encoder"], o["lr_decoder"]]
    scaler = torch.amp.GradScaler("cuda", enabled=amp)
    rng = np.random.default_rng(seed)
    start_epoch, best_iou, history = 0, -1.0, []
    if args.resume == "auto" and (out / "last.pt").exists():
        ck = torch.load(out / "last.pt", map_location=device, weights_only=False)
        model.load_state_dict(ck["model"])
        opt.load_state_dict(ck["opt"])
        scaler.load_state_dict(ck["scaler"])
        rng.bit_generator.state = ck["rng"]
        torch.set_rng_state(ck["torch_rng"])
        start_epoch, best_iou, history = ck["epoch"] + 1, ck["best_iou"], ck["history"]
        print(f"resumed at epoch {start_epoch}, best val IoU {best_iou:.4f}")

    epochs = int(prof["epochs"])
    if args.resume == "auto" and (out / "last.pt").exists():
        # The schedule length may have been shortened by the time budget; keep it on resume.
        epochs = int(ck.get("epochs", epochs))
    budget_s = float(prof.get("time_budget_min", 0)) * 60
    t0 = time.time()
    stopped_early = False
    best_epoch = next((h["epoch"] for h in history if h.get("val_iou") == best_iou), -1)
    for epoch in range(start_epoch, epochs):
        if epoch >= epochs:
            # ``range`` is fixed at loop start; the time budget may shorten ``epochs`` below.
            break
        te = time.time()
        samples = epoch_samples(rng, train, prof["crop"], prof["crops_per_chip"], cfg["augment"])
        bs = int(prof["batch"])
        nb = max(len(samples) // bs, 1)
        losses = []
        for b in range(nb):
            f = lr_factor(epoch + b / nb, int(prof["warmup_epochs"]), epochs)
            for g, lr in zip(opt.param_groups, base_lrs, strict=True):
                g["lr"] = lr * f
            batch = samples[b * bs : (b + 1) * bs]
            x = torch.from_numpy(np.stack([s[0] for s in batch])).to(device)
            y = torch.from_numpy(np.stack([s[1] for s in batch]).astype(np.int64))[:, None]
            y = y.to(device)
            with torch.autocast(device_type=device, enabled=amp):
                z = model(x)
            loss = masked_loss(z.float(), y, cfg["loss"]["bce_weight"], cfg["loss"]["dice_weight"])
            opt.zero_grad(set_to_none=True)
            scaler.scale(loss).backward()
            scaler.step(opt)
            scaler.update()
            losses.append(float(loss.detach()))
        if budget_s > 0 and epoch == 1 and start_epoch <= 1:
            # Fit the cosine schedule into the time budget (CPU profile): the number of epochs
            # that fit is estimated from the second epoch (the first one carries warm-up
            # overhead) and logged.
            per_epoch = (time.time() - te) * 1.10  # validation overhead
            fit = max(2 + int((budget_s - (time.time() - t0)) // per_epoch), 2)
            if fit < epochs:
                print(f"time budget: schedule shortened from {epochs} to {fit} epochs", flush=True)
                epochs = fit
        rec: dict[str, Any] = {
            "epoch": epoch,
            "train_loss": float(np.mean(losses)),
            "epoch_s": round(time.time() - te, 1),
        }
        elapsed = time.time() - t0
        last = epoch == epochs - 1
        over = budget_s > 0 and elapsed + 2 * rec["epoch_s"] > budget_s
        if (epoch + 1) % int(prof["val_every"]) == 0 or last or over:
            m = evaluate(model, valid)
            rec.update({"val_iou": m["iou"], "val_f1": m["f1"]})
            if m["iou"] > best_iou:
                best_iou, best_epoch = m["iou"], epoch
                torch.save({"model": model.state_dict(), "epoch": epoch}, out / "best.pt")
        history.append(rec)
        print(json.dumps(rec), flush=True)
        if (epoch + 1) % int(prof["ckpt_every"]) == 0 or last or over:
            torch.save(
                {
                    "model": model.state_dict(),
                    "opt": opt.state_dict(),
                    "scaler": scaler.state_dict(),
                    "rng": rng.bit_generator.state,
                    "torch_rng": torch.get_rng_state(),
                    "epoch": epoch,
                    "epochs": epochs,
                    "best_iou": best_iou,
                    "history": history,
                },
                out / "last.pt",
            )
        if over and not last:
            stopped_early = True
            print(f"time budget reached after epoch {epoch}", flush=True)
            break

    log = {
        "profile": args.profile,
        "profile_config": prof,
        "seed": seed,
        "git_commit": git_commit(),
        "device": device,
        "cpu": platform.processor(),
        "torch": torch.__version__,
        "smp": __import__("segmentation_models_pytorch").__version__,
        "pretrained": "imagenet" if not args.no_pretrained else None,
        "n_train_chips": len(train),
        "n_valid_chips": len(valid),
        "effective_epochs": epochs,
        "best_epoch": best_epoch,
        "best_val_iou": best_iou,
        "wall_time_s": round(time.time() - t0, 1),
        "stopped_early_by_time_budget": stopped_early,
        "history": history,
        "preprocess": pre,
    }
    runs = HERE / "runs"
    runs.mkdir(exist_ok=True)
    if args.profile != "smoke":
        (runs / f"{args.profile}.json").write_text(json.dumps(log, indent=2))
    (out / "run.json").write_text(json.dumps(log, indent=2))
    print(f"best val IoU {best_iou:.4f} at epoch {best_epoch}; wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
