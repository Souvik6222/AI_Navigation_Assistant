import json

def extract(filepath):
    try:
        with open(filepath, 'r') as f:
            raw = f.read()
        start = raw.find('{')
        data = json.loads(raw[start:])
        urls = data.get('urls', [])
        for r in urls:
            fn = r.get('filename', '')
            if 'cp314' in fn and 'linux' in fn and 'x86_64' in fn:
                return r.get('url')
    except Exception as e:
        print(f"Error parsing {filepath}: {e}")
    return None

print("onnx 1.18.0:", extract('/home/vista/.gemini/antigravity-ide/brain/bfc6a478-ed38-49ff-9a97-0f67a735efc4/.system_generated/steps/117/content.md'))
print("onnxruntime-gpu 1.26.0:", extract('/home/vista/.gemini/antigravity-ide/brain/bfc6a478-ed38-49ff-9a97-0f67a735efc4/.system_generated/steps/116/content.md'))
