"""Download SoccerTrack v2, match 117093 (first half), from Hugging Face into data/soccertrack/117093/.

For a machine that doesn't have the data yet. The dataset is gated: the account behind the token has to
have accepted its terms. Put the read token in the repo-root `.env` as HF_TOKEN=... (the file is ignored
by git) or set it as an environment variable. Files already in place are skipped; an interrupted
download resumes.

    video\\.venv\\Scripts\\python video\\finetune\\fetch_data.py               # about 6 GB
    video\\.venv\\Scripts\\python video\\finetune\\fetch_data.py --small-only  # the MOT boxes and other small files

SoccerTrack v2 is CC BY 4.0 (Scott et al., arXiv:2508.01802): credit it wherever results are shown.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import clip  # noqa: E402

REPO = "atomscott/soccertrack-v2"
M = clip.MATCH
# The three big files go where the pipeline expects them; the small ones keep their repo paths under hf/.
BIG = {
    f"videos/{M}/{M}_panorama_1st_half.mp4": clip.VIDEO,  # 3.35 GB
    f"gsr/{M}/{M}_1st.json": clip.GSR,  # 2.71 GB
    f"bas/{M}/{M}_12_class_events.json": clip.BAS,  # 0.5 MB
}
SMALL = [
    f"mot/{M}.txt",  # 6.2 MB: tight boxes for the first four minutes (the fine-tuning labels)
    f"ball/{M}_1st_ball.npz", "README.md", "CHANGES_v1_1.md", "CHANGES_v1_2.md",
    f"raw/{M}/{M}_homography.npy", f"raw/{M}/{M}_camera_intrinsics.npz", f"raw/{M}/{M}_keypoints.json",
    f"raw/{M}/{M}_padding_info.csv", f"raw/{M}/{M}_player_nodes.csv",
]


def token() -> str:
    if os.environ.get("HF_TOKEN"):
        return os.environ["HF_TOKEN"]
    env = clip.ROOT / ".env"
    if env.exists():
        from dotenv import dotenv_values

        value = dotenv_values(env).get("HF_TOKEN")
        if value:
            return value
    raise SystemExit("no Hugging Face token: put HF_TOKEN=... in the repo-root .env, or set the HF_TOKEN variable")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--small-only", action="store_true", help="skip the video and the GSR file")
    args = ap.parse_args()
    from huggingface_hub import hf_hub_download

    tok = token()
    hf = clip.SOURCE / "hf"
    for name in SMALL:
        if (hf / name).exists():
            print(f"have {name}")
            continue
        hf_hub_download(REPO, name, repo_type="dataset", token=tok, local_dir=hf)
        print(f"got  {name}")
    if args.small_only:
        return
    staging = clip.SOURCE / "_download"
    for name, target in BIG.items():
        if target.exists():
            print(f"have {target.name}")
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        path = hf_hub_download(REPO, name, repo_type="dataset", token=tok, local_dir=staging)
        Path(path).replace(target)
        print(f"got  {target.name}")
    shutil.rmtree(staging, ignore_errors=True)


if __name__ == "__main__":
    main()
