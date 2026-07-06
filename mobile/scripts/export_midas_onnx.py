"""Export MiDaS v2.1 Small to ONNX format for mobile/ARM deployment.
Usage: python export_midas_onnx.py [--output models/midas_v21_small_256.onnx]
"""
import argparse
import os
import sys

import torch
import torch.onnx

MIDAS_CACHE = os.path.expanduser(
    "~/.cache/torch/hub/checkpoints/midas_v21_small_256.pt"
)


def export(output_path: str):
    output_path = os.path.abspath(output_path)
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    print(f"Loading MiDaS_small from torch hub...")
    model = torch.hub.load(
        "intel-isl/MiDaS", "MiDaS_small", trust_repo=True, skip_validation=True
    )
    model.eval()

    dummy = torch.randn(1, 3, 256, 256)

    print(f"Exporting to ONNX (opset 12): {output_path}")
    # Use dynamo=False for broader opset-12 compatibility
    torch.onnx.export(
        model,
        dummy,
        output_path,
        input_names=["input"],
        output_names=["depth"],
        dynamic_axes={
            "input": {0: "batch", 2: "height", 3: "width"},
            "depth": {0: "batch", 2: "height", 3: "width"},
        },
        opset_version=12,
        do_constant_folding=True,
        dynamo=False,
    )
    size_mb = os.path.getsize(output_path) / (1024 * 1024)
    print(f"Done! {output_path} ({size_mb:.1f} MB)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Export MiDaS to ONNX")
    parser.add_argument(
        "--output",
        default=os.path.join(
            os.path.dirname(__file__), "..", "models", "midas_v21_small_256.onnx"
        ),
        help="Output ONNX model path",
    )
    args = parser.parse_args()
    sys.exit(export(args.output))
