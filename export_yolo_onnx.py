from ultralytics import YOLO
import os

def export_model(model_name):
    print(f"Loading {model_name}...")
    model = YOLO(model_name)
    
    print(f"Exporting {model_name} to ONNX...")
    # opset=12 is widely supported by ONNX Runtime and OpenCV
    # dynamic=True allows variable batch sizes and image dimensions if needed, 
    # but for mobile/C++ fixed size (dynamic=False) is often safer and faster.
    # We will use the default static shape (1, 3, 640, 640) which is standard.
    success = model.export(format="onnx", opset=12)
    print(f"Exported to: {success}")

if __name__ == "__main__":
    os.makedirs("yolomodel", exist_ok=True)
    
    export_model("yolov8n.pt")
    export_model("yolov8s.pt")
    
    # Move them to yolomodel folder if they aren't there already
    for model_file in ["yolov8n.onnx", "yolov8s.onnx"]:
        if os.path.exists(model_file):
            os.rename(model_file, f"yolomodel/{model_file}")
            print(f"Moved {model_file} to yolomodel/")
    
    print("Done! Both models exported successfully.")
