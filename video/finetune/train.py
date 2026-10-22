"""Fine-tune RF-DETR small on the tiled MOT dataset (run on a machine with an NVIDIA GPU).

Starts from the COCO weights, replaces the head with one class (`player`) and trains on the tiles
from build_dataset.py. The checkpoint that scores best on the `valid` split is kept (`valid` is
a different stretch of the clip from `train`, with a gap between them). Nothing here touches the
benchmark clip.

    video\\.venv\\Scripts\\python video\\finetune\\build_dataset.py --limit 3 --out data\\finetune\\smoke
    video\\.venv\\Scripts\\python video\\finetune\\train.py --smoke --dataset data\\finetune\\smoke   # does it run?
    video\\.venv\\Scripts\\python video\\finetune\\train.py                                          # the real run

Needs the training extras: pip install "rfdetr[train]==1.11.2". Outputs go to
data/finetune/runs/<name>/, including `train_summary.json` and the checkpoints.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import clip  # noqa: E402

DATASET = clip.ROOT / "data" / "finetune" / clip.MATCH
RUNS = clip.ROOT / "data" / "finetune" / "runs"


def train_options(args: argparse.Namespace, output_dir: Path) -> dict:
    """The keyword arguments for RFDETR.train(), kept apart so they can be checked without training."""
    return {
        "dataset_dir": str(args.dataset),
        "output_dir": str(output_dir),
        "epochs": 1 if args.smoke else args.epochs,
        "batch_size": 2 if args.smoke else args.batch_size,
        "grad_accum_steps": 1 if args.smoke else args.grad_accum,
        "lr": args.lr,
        "num_workers": 0 if args.smoke else args.workers,
        "early_stopping": True,
        "early_stopping_patience": args.patience,
        "tensorboard": False,
        "class_names": ["player"],
        "seed": 7,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dataset", type=Path, default=DATASET)
    ap.add_argument("--name", default=time.strftime("rfdetr-small-%Y%m%d-%H%M"))
    ap.add_argument("--epochs", type=int, default=30)
    ap.add_argument("--batch-size", type=int, default=8, help="lower it if the GPU runs out of memory")
    ap.add_argument("--grad-accum", type=int, default=2, help="effective batch = batch size x this")
    ap.add_argument("--lr", type=float, default=1e-4)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--patience", type=int, default=8, help="epochs without improvement before stopping")
    ap.add_argument("--smoke", action="store_true", help="one epoch with a tiny batch, to check it runs")
    args = ap.parse_args()

    import torch

    if not torch.cuda.is_available():
        print("warning: no CUDA GPU found; this will be very slow (check the PyTorch CUDA install)", file=sys.stderr)
    output_dir = RUNS / args.name
    options = train_options(args, output_dir)

    from rfdetr import RFDETRSmall

    model = RFDETRSmall()  # COCO weights, downloaded on first use
    started = time.perf_counter()
    model.train(**options)
    summary = {
        "model": "RF-DETR small", "from": "COCO pre-trained", "dataset": str(args.dataset),
        "options": {k: v for k, v in options.items() if k not in ("dataset_dir", "output_dir")},
        "gpu": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
        "minutes": round((time.perf_counter() - started) / 60, 1),
        "checkpoints": sorted(p.name for p in output_dir.glob("*.pth")),
        "dataset_counts": json.loads((args.dataset / "summary.json").read_text(encoding="utf-8"))
        if (args.dataset / "summary.json").exists() else None,
    }
    (output_dir / "train_summary.json").write_text(json.dumps(summary, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
