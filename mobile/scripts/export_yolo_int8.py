#!/usr/bin/env python3
"""
Export YOLOv8 models to INT8-quantized ONNX format.

This script performs two steps:
1. Export .pt models to FP32 ONNX (if not already exported)
2. Apply weight-only INT8 quantization using the ONNX library

Weight-only quantization reduces model size by ~4x without needing
calibration data. ONNX Runtime dequantizes weights at inference time,
providing most of the speed benefit on ARM with zero calibration setup.

Usage:
    python export_yolo_int8.py

Models are read from /yolomodel/ and exported to /mobile/models/
"""

import os
import sys
import shutil
from pathlib import Path

import numpy as np
import onnx
from onnx import numpy_helper, TensorProto, helper


def quantize_weights_int8(model_path: str, output_path: str):
    """
    Apply weight-only INT8 quantization to an ONNX model.
    
    For each large float32 initializer (weight tensor), converts it to int8
    with per-channel scale/zero-point. This is functionally equivalent to
    onnxruntime.quantization.quantize_dynamic() but uses only the onnx library.
    
    Weights are stored as INT8 + scale + zero_point. ONNX Runtime automatically
    dequantizes them during inference using the DequantizeLinear op.
    """
    print(f"  Loading ONNX model: {model_path}")
    model = onnx.load(model_path)
    graph = model.graph

    initializer_names = {init.name for init in graph.initializer}
    
    # Collect float32 weight tensors that are large enough to benefit from quantization
    # Skip biases (1D) and very small tensors
    weights_to_quantize = []
    for init in graph.initializer:
        if init.data_type == TensorProto.FLOAT:
            arr = numpy_helper.to_array(init)
            # Only quantize tensors > 1KB (skip small biases)
            if arr.nbytes > 1024 and len(arr.shape) >= 2:
                weights_to_quantize.append(init)
    
    if not weights_to_quantize:
        print("  No suitable weights found for quantization")
        shutil.copy2(model_path, output_path)
        return
    
    print(f"  Quantizing {len(weights_to_quantize)} weight tensors to INT8...")
    
    new_initializers = []
    nodes_to_add = []
    initializers_to_remove = set()
    input_rewire = {}  # old_name -> new DequantizeLinear output name
    
    for idx, init in enumerate(weights_to_quantize):
        arr = numpy_helper.to_array(init).astype(np.float32)
        old_name = init.name
        
        # Per-tensor symmetric quantization
        abs_max = np.max(np.abs(arr))
        if abs_max < 1e-10:
            continue  # Skip near-zero tensors
        
        scale = abs_max / 127.0
        quantized = np.clip(np.round(arr / scale), -128, 127).astype(np.int8)
        
        # Create new initializers for the quantized weight, scale, and zero_point
        q_name = f"{old_name}_quantized"
        s_name = f"{old_name}_scale"
        zp_name = f"{old_name}_zero_point"
        dq_output_name = f"{old_name}_dequantized"
        
        q_tensor = numpy_helper.from_array(quantized, name=q_name)
        s_tensor = numpy_helper.from_array(np.array(scale, dtype=np.float32), name=s_name)
        zp_tensor = numpy_helper.from_array(np.array(0, dtype=np.int8), name=zp_name)
        
        new_initializers.extend([q_tensor, s_tensor, zp_tensor])
        
        # Create DequantizeLinear node: int8_weight -> float32_weight
        dq_node = helper.make_node(
            "DequantizeLinear",
            inputs=[q_name, s_name, zp_name],
            outputs=[dq_output_name],
            name=f"dequantize_{idx}"
        )
        nodes_to_add.append(dq_node)
        
        initializers_to_remove.add(old_name)
        input_rewire[old_name] = dq_output_name
    
    # Remove original float32 initializers
    new_graph_initializers = [
        init for init in graph.initializer 
        if init.name not in initializers_to_remove
    ]
    new_graph_initializers.extend(new_initializers)
    
    # Rewire node inputs to use dequantized outputs
    for node in graph.node:
        for i, inp in enumerate(node.input):
            if inp in input_rewire:
                node.input[i] = input_rewire[inp]
    
    # Insert DequantizeLinear nodes at the beginning of the graph
    all_nodes = list(nodes_to_add) + list(graph.node)
    
    # Build new graph
    new_graph = helper.make_graph(
        all_nodes,
        graph.name,
        graph.input,
        graph.output,
        initializer=new_graph_initializers,
    )
    
    # Preserve graph-level value_info
    new_graph.value_info.extend(graph.value_info)
    
    new_model = helper.make_model(new_graph, opset_imports=model.opset_import)
    new_model.ir_version = model.ir_version
    
    # Copy metadata
    for prop in model.metadata_props:
        new_model.metadata_props.append(prop)
    
    print(f"  Saving quantized model: {output_path}")
    onnx.save(new_model, output_path)
    
    # Report size savings
    orig_size = os.path.getsize(model_path) / (1024 * 1024)
    quant_size = os.path.getsize(output_path) / (1024 * 1024)
    reduction = (1 - quant_size / orig_size) * 100
    print(f"  Original:  {orig_size:.1f} MB")
    print(f"  INT8:      {quant_size:.1f} MB")
    print(f"  Reduction: {reduction:.0f}%")


def ensure_onnx_exists(pt_path: str, onnx_dir: str) -> str:
    """Export .pt to FP32 ONNX if the ONNX file doesn't already exist."""
    model_name = Path(pt_path).stem  # e.g. "yolov8n"
    onnx_path = os.path.join(onnx_dir, f"{model_name}.onnx")
    
    if os.path.exists(onnx_path):
        print(f"  FP32 ONNX already exists: {onnx_path}")
        return onnx_path
    
    print(f"  Exporting {model_name}.pt → FP32 ONNX...")
    from ultralytics import YOLO
    model = YOLO(pt_path)
    export_path = model.export(format="onnx", opset=12, imgsz=640)
    
    if export_path and os.path.exists(export_path):
        if str(export_path) != onnx_path:
            shutil.move(str(export_path), onnx_path)
        return onnx_path
    else:
        return None


def main():
    script_dir = Path(__file__).resolve().parent
    project_root = script_dir.parent.parent  # mobile/scripts -> project root

    yolo_dir = project_root / "yolomodel"
    output_dir = script_dir.parent / "models"
    os.makedirs(output_dir, exist_ok=True)

    models = {
        "yolov8n": yolo_dir / "yolov8n.pt",
        "yolov8s": yolo_dir / "yolov8s.pt",
    }

    print("=" * 60)
    print("YOLOv8 INT8 Weight Quantization Export")
    print("=" * 60)
    print(f"Source directory:  {yolo_dir}")
    print(f"Output directory:  {output_dir}")

    all_exist = True
    for name, path in models.items():
        exists = os.path.exists(path)
        status = "✓" if exists else "✗ MISSING"
        print(f"  {name}: {path} [{status}]")
        if not exists:
            all_exist = False

    if not all_exist:
        print("\nERROR: Some source .pt models are missing.")
        sys.exit(1)

    results = {}
    for name, pt_path in models.items():
        print(f"\n{'='*60}")
        print(f"Processing {name}...")
        print(f"{'='*60}")
        
        # Step 1: Ensure FP32 ONNX exists (use existing ones from yolomodel/)
        fp32_onnx = str(yolo_dir / f"{name}.onnx")
        if not os.path.exists(fp32_onnx):
            fp32_onnx = ensure_onnx_exists(str(pt_path), str(yolo_dir))
        
        if not fp32_onnx or not os.path.exists(fp32_onnx):
            print(f"  ERROR: Could not get FP32 ONNX for {name}")
            results[name] = None
            continue
        
        print(f"  FP32 ONNX: {fp32_onnx}")
        
        # Step 2: Quantize to INT8
        int8_path = str(output_dir / f"{name}_int8.onnx")
        try:
            quantize_weights_int8(fp32_onnx, int8_path)
            results[name] = int8_path
        except Exception as e:
            print(f"  ERROR: Quantization failed for {name}: {e}")
            import traceback
            traceback.print_exc()
            results[name] = None

    # Summary
    print(f"\n{'='*60}")
    print("Export Summary")
    print(f"{'='*60}")
    
    success_count = 0
    for name, path in results.items():
        if path:
            print(f"  ✓ {name}_int8.onnx → {path}")
            success_count += 1
        else:
            print(f"  ✗ {name} — FAILED")

    print(f"\n{success_count}/{len(models)} models exported successfully.")

    if success_count > 0:
        print("\nTo use INT8 models, update config.yaml:")
        print('  yolo_model_path: "models/yolov8n_int8.onnx"')

    return 0 if success_count == len(models) else 1


if __name__ == "__main__":
    sys.exit(main())
