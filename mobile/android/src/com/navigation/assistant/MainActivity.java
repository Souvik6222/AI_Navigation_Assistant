package com.navigation.assistant;

import android.Manifest;
import android.content.pm.PackageManager;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.speech.tts.TextToSpeech;
import android.util.Log;
import android.util.Size;
import android.view.View;
import android.widget.Button;
import android.widget.ScrollView;
import android.widget.TextView;
import android.widget.Toast;

import androidx.annotation.NonNull;
import androidx.appcompat.app.AlertDialog;
import androidx.appcompat.app.AppCompatActivity;
import androidx.appcompat.app.AppCompatDelegate;
import androidx.camera.core.AspectRatio;
import androidx.camera.core.Camera;
import androidx.camera.core.CameraSelector;
import androidx.camera.core.ImageAnalysis;
import androidx.camera.core.ImageProxy;
import androidx.camera.core.Preview;
import androidx.camera.lifecycle.ProcessCameraProvider;
import androidx.camera.view.PreviewView;
import androidx.core.app.ActivityCompat;
import androidx.core.content.ContextCompat;

import com.google.common.util.concurrent.ListenableFuture;

import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.nio.ByteBuffer;
import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.LinkedList;
import java.util.Locale;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;

public class MainActivity extends AppCompatActivity implements TextToSpeech.OnInitListener {

    private static final String TAG = "NavAssistant";
    private static final int CAMERA_PERMISSION_CODE = 100;

    private TextToSpeech tts;
    private NativePipeline nativePipeline;
    private PreviewView cameraPreview;
    private OverlayView overlayView;
    private View floatingBar;
    private Button btnVision, btnTorch, btnLogsToggle, btnSettings;
    private boolean isTorchOn = false;
    private TextView logTextView;
    private ScrollView logScrollView;
    private boolean ttsReady = false;
    private boolean isHindi = false;

    // Logging State
    private boolean showingDevLogs = false;
    private LinkedList<String> normalLogs = new LinkedList<>();
    private LinkedList<String> devLogs = new LinkedList<>();
    private static final int MAX_LOGS = 100;
    // Used to suppress navigation TTS while LLM vision description is playing
    private long lastVisionSpeakMs = 0;
    private static final long VISION_LOCK_MS = 8000; // suppress TTS for 8s after LLM speaks
    private final SimpleDateFormat timeFormat = new SimpleDateFormat("HH:mm:ss", Locale.US);

    // CameraX
    private ExecutorService cameraExecutor;
    private ProcessCameraProvider cameraProvider;
    private boolean useFrontCamera = false;
    private Camera activeCamera;
    private volatile boolean isSwitchingCamera = false;

    private Handler hideHandler = new Handler(Looper.getMainLooper());
    private Runnable hideRunnable = () -> {
        if (floatingBar != null) {
            floatingBar.animate().alpha(0.0f).setDuration(300)
                .withEndAction(() -> floatingBar.setVisibility(View.GONE));
        }
    };

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_main);

        cameraPreview = findViewById(R.id.camera_preview);
        overlayView   = findViewById(R.id.overlay_view);
        floatingBar   = findViewById(R.id.floating_ui_container);
        btnVision     = findViewById(R.id.btn_vision);
        btnTorch      = findViewById(R.id.btn_torch);
        btnLogsToggle = findViewById(R.id.btn_logs_toggle);
        btnSettings   = findViewById(R.id.btn_settings);

        // Torch button: toggle flashlight
        btnTorch.setOnClickListener(v -> {
            resetHideTimer();
            if (activeCamera != null && activeCamera.getCameraInfo().hasFlashUnit()) {
                isTorchOn = !isTorchOn;
                activeCamera.getCameraControl().enableTorch(isTorchOn);
                btnTorch.setText(isTorchOn ? "Torch ON" : "Torch");
                Toast.makeText(this, isTorchOn ? "Torch Enabled" : "Torch Disabled", Toast.LENGTH_SHORT).show();
            } else {
                Toast.makeText(this, "Torch not available", Toast.LENGTH_SHORT).show();
            }
        });
        logTextView   = findViewById(R.id.log_text_view);
        logScrollView = findViewById(R.id.log_scroll_view);

        cameraExecutor = Executors.newSingleThreadExecutor();

        // Tap screen to show floating bar
        cameraPreview.setOnClickListener(v -> showFloatingBar());
        overlayView.setOnClickListener(v -> showFloatingBar());

        // Vision button: toggle front/back camera
        btnVision.setOnClickListener(v -> {
            resetHideTimer();
            if (isSwitchingCamera) return;
            useFrontCamera = !useFrontCamera;
            Toast.makeText(this, "Switching to " + (useFrontCamera ? "Front" : "Back") + " Camera",
                    Toast.LENGTH_SHORT).show();
            if (cameraProvider != null) switchCamera();
        });

        // Toggle Logs button
        btnLogsToggle.setOnClickListener(v -> {
            resetHideTimer();
            showingDevLogs = !showingDevLogs;
            btnLogsToggle.setText(showingDevLogs ? "Dev Logs" : "Normal Logs");
            refreshLogView();
        });

        btnSettings.setOnClickListener(v -> { resetHideTimer(); showSettingsDialog(); });

        resetHideTimer();
        tts = new TextToSpeech(this, this, "com.github.olga_yakovleva.rhvoice.android");
        // Note: if RHVoice is not installed, this will silently fail and onInit gets ERROR.
        // We handle that by falling back to system default TTS in onInit.

        if (ContextCompat.checkSelfPermission(this, Manifest.permission.CAMERA)
                != PackageManager.PERMISSION_GRANTED) {
            ActivityCompat.requestPermissions(this,
                    new String[]{Manifest.permission.CAMERA}, CAMERA_PERMISSION_CODE);
        } else {
            copyAssetsAndStart();
        }
    }

    @Override
    public void onInit(int status) {
        if (status == TextToSpeech.SUCCESS) {
            // Try setting English locale; if RHVoice doesn't support it, it won't crash
            int langResult = tts.setLanguage(Locale.ENGLISH);
            if (langResult == TextToSpeech.LANG_MISSING_DATA
                    || langResult == TextToSpeech.LANG_NOT_SUPPORTED) {
                // RHVoice English (Russia) — try with a broader locale
                tts.setLanguage(new Locale("en"));
            }
            tts.setSpeechRate(0.85f);
            ttsReady = true;
            appendLog(normalLogs, "System: TTS ready (RHVoice)");
            Log.d(TAG, "TTS initialized with RHVoice");
        } else {
            // RHVoice wasn't available — retry with system default TTS
            Log.w(TAG, "RHVoice TTS init failed (status=" + status + "), falling back to system default");
            tts = new TextToSpeech(this, status2 -> {
                if (status2 == TextToSpeech.SUCCESS) {
                    tts.setLanguage(Locale.ENGLISH);
                    tts.setSpeechRate(0.85f);
                    ttsReady = true;
                    appendLog(normalLogs, "System: TTS ready (system default)");
                } else {
                    appendLog(normalLogs, "System: TTS FAILED — no TTS engine available!");
                    Log.e(TAG, "System default TTS also failed");
                }
            });
        }
    }

    public void speak(String text) {
        // Suppress regular nav alerts while LLM vision description is playing
        if (System.currentTimeMillis() - lastVisionSpeakMs < VISION_LOCK_MS) return;
        if (ttsReady && tts != null) tts.speak(text, TextToSpeech.QUEUE_FLUSH, null, null);
        appendLog(normalLogs, "TTS: " + text);
    }

    public void speakUrgent(String text) {
        // Urgent alerts always break through, even during vision description
        lastVisionSpeakMs = 0;
        if (ttsReady && tts != null) tts.speak(text, TextToSpeech.QUEUE_FLUSH, null, null);
        appendLog(normalLogs, "TTS URGENT: " + text);
    }

    public void speakVision(String text) {
        // LLM vision description — locks out regular nav TTS for VISION_LOCK_MS
        lastVisionSpeakMs = System.currentTimeMillis();
        if (ttsReady && tts != null) tts.speak(text, TextToSpeech.QUEUE_FLUSH, null, null);
        appendLog(normalLogs, "Vision: " + text);
    }

    private void appendLog(LinkedList<String> logList, String message) {
        String time = timeFormat.format(new Date());
        String entry = "[" + time + "] " + message;
        
        runOnUiThread(() -> {
            logList.add(entry);
            if (logList.size() > MAX_LOGS) {
                logList.removeFirst();
            }
            if ((logList == devLogs && showingDevLogs) || (logList == normalLogs && !showingDevLogs)) {
                refreshLogView();
            }
        });
    }

    private void refreshLogView() {
        LinkedList<String> activeLogs = showingDevLogs ? devLogs : normalLogs;
        StringBuilder sb = new StringBuilder();
        for (String log : activeLogs) {
            sb.append(log).append("\n");
        }
        logTextView.setText(sb.toString());
        logScrollView.post(() -> logScrollView.fullScroll(View.FOCUS_DOWN));
    }

    // ─── Model extraction ─────────────────────────────────────────────────────

    private void copyAssetsAndStart() {
        appendLog(normalLogs, "System: Extracting AI Models...");
        new Thread(() -> {
            try {
                String[] models = {"yolov8n_int8.onnx", "midas_v21_small_256.onnx"};
                for (String model : models) {
                    File outFile = new File(getFilesDir(), model);
                    if (!outFile.exists()) {
                        Log.d(TAG, "Extracting model: " + model);
                        appendLog(devLogs, "Extracting " + model);
                        InputStream in = getAssets().open(model);
                        OutputStream out = new FileOutputStream(outFile);
                        byte[] buffer = new byte[8192];
                        int read;
                        while ((read = in.read(buffer)) != -1) out.write(buffer, 0, read);
                        in.close(); out.flush(); out.close();
                    }
                }
                appendLog(normalLogs, "System: Models ready. Starting engine.");
                runOnUiThread(this::startPipeline);
            } catch (IOException e) {
                Log.e(TAG, "Failed to copy models", e);
                appendLog(normalLogs, "System: FATAL error copying models");
            }
        }).start();
    }

    private void startPipeline() {
        nativePipeline = new NativePipeline(this);
        nativePipeline.start(
            getAssets(),
            getFilesDir().getAbsolutePath(),
            this::speak,
            this::speakUrgent
        );
        Log.d(TAG, "Native pipeline started");
        setupCameraX();
    }

    // ─── CameraX ──────────────────────────────────────────────────────────────

    private void setupCameraX() {
        ListenableFuture<ProcessCameraProvider> future =
                ProcessCameraProvider.getInstance(this);
        future.addListener(() -> {
            try {
                cameraProvider = future.get();
                bindCameraX();
            } catch (ExecutionException | InterruptedException e) {
                Log.e(TAG, "CameraX provider failed", e);
            }
        }, ContextCompat.getMainExecutor(this));
    }

    private void switchCamera() {
        isSwitchingCamera = true;
        ExecutorService oldExecutor = cameraExecutor;
        cameraExecutor = Executors.newSingleThreadExecutor();
        oldExecutor.shutdown();
        new Thread(() -> {
            try { oldExecutor.awaitTermination(600, TimeUnit.MILLISECONDS); }
            catch (InterruptedException ignored) {}
            runOnUiThread(() -> { bindCameraX(); isSwitchingCamera = false; });
        }).start();
    }

    private void bindCameraX() {
        if (cameraProvider == null) return;
        cameraProvider.unbindAll();

        CameraSelector selector = useFrontCamera
                ? CameraSelector.DEFAULT_FRONT_CAMERA
                : CameraSelector.DEFAULT_BACK_CAMERA;

        // Preview use case — renders live camera frames into PreviewView
        Preview preview = new Preview.Builder()
                .setTargetAspectRatio(AspectRatio.RATIO_16_9)
                .build();
        preview.setSurfaceProvider(cameraPreview.getSurfaceProvider());

        // ImageAnalysis — delivers raw YUV frames to C++ pipeline for AI processing
        ImageAnalysis imageAnalysis = new ImageAnalysis.Builder()
                .setTargetAspectRatio(AspectRatio.RATIO_16_9)
                .setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST)
                .setOutputImageFormat(ImageAnalysis.OUTPUT_IMAGE_FORMAT_YUV_420_888)
                .build();

        imageAnalysis.setAnalyzer(cameraExecutor, image -> {
            if (nativePipeline != null && !isSwitchingCamera) {
                byte[] nv21 = yuv420ToNv21(image);
                // Pipeline processes at the image's dimensions, e.g. 320x240
                nativePipeline.processFrame(nv21, image.getWidth(), image.getHeight(), image.getImageInfo().getRotationDegrees());
            }
            image.close();
        });

        try {
            activeCamera = cameraProvider.bindToLifecycle(this, selector, preview, imageAnalysis);
            if (activeCamera.getCameraInfo().hasFlashUnit()) {
                activeCamera.getCameraControl().enableTorch(isTorchOn);
            }
            appendLog(normalLogs, "System: Camera connected (" + (useFrontCamera ? "front" : "back") + ")");
            Log.d(TAG, "CameraX bound (" + (useFrontCamera ? "front" : "back") + ")");
        } catch (Exception e) {
            appendLog(normalLogs, "System: Camera error");
            Log.e(TAG, "CameraX bindToLifecycle failed", e);
        }
    }

    private byte[] yuv420ToNv21(ImageProxy image) {
        int width  = image.getWidth();
        int height = image.getHeight();

        ImageProxy.PlaneProxy yPlane = image.getPlanes()[0];
        ImageProxy.PlaneProxy uPlane = image.getPlanes()[1];
        ImageProxy.PlaneProxy vPlane = image.getPlanes()[2];

        ByteBuffer yBuf = yPlane.getBuffer();
        ByteBuffer uBuf = uPlane.getBuffer();
        ByteBuffer vBuf = vPlane.getBuffer();

        byte[] nv21 = new byte[width * height * 3 / 2];

        int yRowStride = yPlane.getRowStride();
        int ySize = width * height;
        if (yRowStride == width) {
            yBuf.get(nv21, 0, ySize);
        } else {
            for (int row = 0; row < height; row++) {
                yBuf.position(row * yRowStride);
                yBuf.get(nv21, row * width, width);
            }
        }

        int uvRowStride   = vPlane.getRowStride();
        int uvPixelStride = vPlane.getPixelStride();
        int uvOffset = ySize;
        int uvHeight = height / 2;

        if (uvPixelStride == 2) {
            for (int row = 0; row < uvHeight; row++) {
                vBuf.position(row * uvRowStride);
                int len = Math.min(width, vBuf.remaining());
                vBuf.get(nv21, uvOffset + row * width, len);
            }
        } else {
            byte[] vBytes = new byte[vBuf.remaining()];
            byte[] uBytes = new byte[uBuf.remaining()];
            vBuf.get(vBytes); uBuf.get(uBytes);
            int uvWidth = width / 2;
            for (int i = 0; i < uvHeight * uvWidth; i++) {
                nv21[uvOffset + i * 2]     = vBytes[i];
                nv21[uvOffset + i * 2 + 1] = uBytes[i];
            }
        }

        return nv21;
    }

    // ─── UI ───────────────────────────────────────────────────────────────────

    private void showFloatingBar() {
        if (floatingBar.getVisibility() != View.VISIBLE) {
            floatingBar.setVisibility(View.VISIBLE);
            floatingBar.setAlpha(0.0f);
            floatingBar.animate().alpha(1.0f).setDuration(300).start();
        }
        resetHideTimer();
    }

    private void resetHideTimer() {
        hideHandler.removeCallbacks(hideRunnable);
        hideHandler.postDelayed(hideRunnable, 8000);
    }

    private void showSettingsDialog() {
        String[] options = {"Toggle Language (EN/HI)", "Toggle Dark Mode", "LLM API Settings", "Open Source Licenses"};
        new AlertDialog.Builder(this)
            .setTitle("Settings")
            .setItems(options, (dialog, which) -> {
                if (which == 0) {
                    if (nativePipeline != null) {
                        nativePipeline.toggleLanguage();
                        isHindi = !isHindi;
                        if (tts != null)
                            tts.setLanguage(isHindi ? new Locale("hi", "IN") : Locale.ENGLISH);
                        Toast.makeText(this, isHindi ? "Language: Hindi" : "Language: English",
                                Toast.LENGTH_SHORT).show();
                    }
                } else if (which == 1) {
                    int cur = AppCompatDelegate.getDefaultNightMode();
                    AppCompatDelegate.setDefaultNightMode(
                        cur == AppCompatDelegate.MODE_NIGHT_YES
                            ? AppCompatDelegate.MODE_NIGHT_NO
                            : AppCompatDelegate.MODE_NIGHT_YES);
                } else if (which == 2) {
                    showApiSettingsDialog();
                } else {
                    Toast.makeText(this,
                        "YOLOv8 (AGPL-3.0)  MiDaS (MIT)  ONNX Runtime (MIT)",
                        Toast.LENGTH_LONG).show();
                }
            }).show();
    }

    private void showApiSettingsDialog() {
        View view = getLayoutInflater().inflate(R.layout.dialog_api_settings, null);
        android.widget.Spinner spinnerProvider = view.findViewById(R.id.spinner_provider);
        View containerBaseUrl = view.findViewById(R.id.container_base_url);
        android.widget.EditText editBaseUrl = view.findViewById(R.id.edit_base_url);
        android.widget.EditText editApiKey = view.findViewById(R.id.edit_api_key);
        android.widget.EditText editModelName = view.findViewById(R.id.edit_model_name);

        String[] providers = {"Groq", "OpenAI", "Custom / Ollama"};
        android.widget.ArrayAdapter<String> adapter = new android.widget.ArrayAdapter<>(this, android.R.layout.simple_spinner_dropdown_item, providers);
        spinnerProvider.setAdapter(adapter);

        android.content.SharedPreferences prefs = getSharedPreferences("llm_prefs", MODE_PRIVATE);
        int savedProvider = prefs.getInt("provider", 0);
        spinnerProvider.setSelection(savedProvider);
        editBaseUrl.setText(prefs.getString("base_url", ""));
        editApiKey.setText(prefs.getString("api_key", ""));
        editModelName.setText(prefs.getString("model_name", "qwen/qwen3.6-27b"));

        spinnerProvider.setOnItemSelectedListener(new android.widget.AdapterView.OnItemSelectedListener() {
            @Override
            public void onItemSelected(android.widget.AdapterView<?> parent, View view, int position, long id) {
                if (position == 2) {
                    containerBaseUrl.setVisibility(View.VISIBLE);
                } else {
                    containerBaseUrl.setVisibility(View.GONE);
                }
            }
            @Override
            public void onNothingSelected(android.widget.AdapterView<?> parent) {}
        });

        new AlertDialog.Builder(this)
            .setTitle("LLM API Settings")
            .setView(view)
            .setPositiveButton("Save", (dialog, which) -> {
                prefs.edit()
                     .putInt("provider", spinnerProvider.getSelectedItemPosition())
                     .putString("base_url", editBaseUrl.getText().toString())
                     .putString("api_key", editApiKey.getText().toString())
                     .putString("model_name", editModelName.getText().toString())
                     .apply();
                Toast.makeText(this, "API Settings Saved", Toast.LENGTH_SHORT).show();
            })
            .setNegativeButton("Cancel", null)
            .show();
    }

    public void requestSceneDescription(String base64Image) {
        new Thread(() -> {
            try {
                android.content.SharedPreferences prefs = getSharedPreferences("llm_prefs", MODE_PRIVATE);
                int providerIndex = prefs.getInt("provider", 0);
                String baseUrl = prefs.getString("base_url", "");
                String apiKey = prefs.getString("api_key", "");
                String modelName = prefs.getString("model_name", "qwen/qwen3.6-27b");
                String[] providerNames = {"Groq", "OpenAI", "Custom"};

                // Warn early if API key is missing for cloud providers
                if (apiKey.isEmpty() && providerIndex < 2) {
                    appendLog(devLogs, "[LLM] SKIP: No API key set for " + providerNames[providerIndex]);
                    return;
                }

                String apiUrl;
                if (providerIndex == 0) apiUrl = "https://api.groq.com/openai/v1/chat/completions";
                else if (providerIndex == 1) apiUrl = "https://api.openai.com/v1/chat/completions";
                else apiUrl = baseUrl.endsWith("/chat/completions") ? baseUrl : (baseUrl.endsWith("/") ? baseUrl + "chat/completions" : baseUrl + "/chat/completions");

                appendLog(devLogs, "[LLM] Sending to " + providerNames[Math.min(providerIndex, 2)] + " / " + modelName);

                org.json.JSONObject payload = new org.json.JSONObject();
                payload.put("model", modelName);
                
                org.json.JSONArray messages = new org.json.JSONArray();
                org.json.JSONObject message = new org.json.JSONObject();
                message.put("role", "user");
                
                org.json.JSONArray content = new org.json.JSONArray();
                org.json.JSONObject textContent = new org.json.JSONObject();
                textContent.put("type", "text");
                
                String lang = getSharedPreferences("app_prefs", MODE_PRIVATE).getString("language", "en");
                String prompt = "Describe this scene very briefly in 1 short sentence for a blind person. Just list the most important objects and their general location. No extra details.";
                if ("hi".equals(lang)) {
                    prompt = "Describe this scene very briefly in 1 short sentence in Hindi for a blind person. Just list the most important objects. No extra details.";
                }
                textContent.put("text", prompt);
                content.put(textContent);
                
                org.json.JSONObject imageContent = new org.json.JSONObject();
                imageContent.put("type", "image_url");
                org.json.JSONObject imageUrl = new org.json.JSONObject();
                imageUrl.put("url", "data:image/jpeg;base64," + base64Image);
                imageContent.put("image_url", imageUrl);
                content.put(imageContent);
                
                message.put("content", content);
                messages.put(message);
                payload.put("messages", messages);
                payload.put("max_tokens", 80);
                
                // Disable thinking/reasoning for Groq models (like Qwen) to bypass latency
                if (providerIndex == 0) {
                    payload.put("reasoning_effort", "none");
                }

                java.net.URL url = new java.net.URL(apiUrl);
                java.net.HttpURLConnection conn = (java.net.HttpURLConnection) url.openConnection();
                conn.setRequestMethod("POST");
                conn.setConnectTimeout(10000);
                conn.setReadTimeout(15000);
                conn.setRequestProperty("Content-Type", "application/json");
                if (!apiKey.isEmpty()) {
                    conn.setRequestProperty("Authorization", "Bearer " + apiKey);
                }
                conn.setDoOutput(true);
                
                java.io.OutputStream os = conn.getOutputStream();
                os.write(payload.toString().getBytes("UTF-8"));
                os.flush();
                os.close();
                
                int responseCode = conn.getResponseCode();
                if (responseCode == java.net.HttpURLConnection.HTTP_OK) {
                    java.io.BufferedReader br = new java.io.BufferedReader(new java.io.InputStreamReader(conn.getInputStream()));
                    StringBuilder sb = new StringBuilder();
                    String line;
                    while ((line = br.readLine()) != null) sb.append(line);
                    br.close();
                    
                    org.json.JSONObject responseJson = new org.json.JSONObject(sb.toString());
                    String description = responseJson.getJSONArray("choices").getJSONObject(0).getJSONObject("message").getString("content");
                    
                    // Strip Qwen/DeepSeek thinking blocks: <think>...</think>
                    description = description.replaceAll("(?s)<think>.*?</think>\\s*", "");
                    
                    final String finalDesc = description;
                    appendLog(devLogs, "[LLM] OK: " + finalDesc.substring(0, Math.min(60, finalDesc.length())) + "...");
                    runOnUiThread(() -> speakVision(finalDesc));
                } else {
                    // Read error body for a useful message (401 = bad key, 429 = rate limit, etc.)
                    java.io.InputStream errStream = conn.getErrorStream();
                    String errBody = "";
                    if (errStream != null) {
                        java.io.BufferedReader errReader = new java.io.BufferedReader(new java.io.InputStreamReader(errStream));
                        StringBuilder errSb = new StringBuilder();
                        String errLine;
                        while ((errLine = errReader.readLine()) != null) errSb.append(errLine);
                        errBody = errSb.toString();
                        try {
                            org.json.JSONObject errJson = new org.json.JSONObject(errBody);
                            if (errJson.has("error")) errBody = errJson.getJSONObject("error").optString("message", errBody);
                        } catch (Exception ignored) {}
                    }
                    String hint = responseCode == 401 ? " (Invalid API key)" :
                                  responseCode == 429 ? " (Rate limit)" :
                                  responseCode == 400 ? " (Bad request)" : "";
                    appendLog(devLogs, "[LLM] Error " + responseCode + hint + ": " + errBody.substring(0, Math.min(80, errBody.length())));
                    Log.e(TAG, "LLM API Error " + responseCode + ": " + errBody);
                }
                conn.disconnect();
            } catch (Exception e) {
                Log.e(TAG, "LLM Request failed", e);
                appendLog(devLogs, "LLM Request failed: " + e.getMessage());
            }
        }).start();
    }

    // ─── Lifecycle ────────────────────────────────────────────────────────────

    @Override
    public void onRequestPermissionsResult(int requestCode,
                                           @NonNull String[] permissions,
                                           @NonNull int[] grantResults) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults);
        if (requestCode == CAMERA_PERMISSION_CODE) {
            if (grantResults.length > 0 && grantResults[0] == PackageManager.PERMISSION_GRANTED)
                copyAssetsAndStart();
            else { Toast.makeText(this, "Camera permission required", Toast.LENGTH_LONG).show(); finish(); }
        }
    }

    @Override
    protected void onDestroy() {
        if (cameraProvider != null) cameraProvider.unbindAll();
        if (cameraExecutor != null) cameraExecutor.shutdown();
        if (nativePipeline != null) nativePipeline.stop();
        if (tts != null) { tts.stop(); tts.shutdown(); }
        super.onDestroy();
    }

    // ─── JNI ─────────────────────────────────────────────────────────────────

    static { System.loadLibrary("ai_navigation_assistant"); }

    private class NativePipeline {
        private final MainActivity activity;

        NativePipeline(MainActivity activity) {
            this.activity = activity;
        }

        native void start(android.content.res.AssetManager assets,
                          String dataPath,
                          SpeakCallback speakCb,
                          SpeakCallback urgentCb);

        native void processFrame(byte[] data, int width, int height, int rotation);

        native void stop();
        native void toggleLanguage();

        // Called by C++ JNI when visual frame is processed
        public void onDetections(float[] boxes) {
            Log.d(TAG, "onDetections received " + (boxes.length / 6) + " boxes");
            // Bounding box coordinates are in the cropped 640x640 square that YOLO processed.
            // Pass 640x640 so OverlayView maps them correctly onto the square region of the preview.
            activity.runOnUiThread(() -> activity.overlayView.setBoundingBoxes(boxes, 640, 640));
        }

        // Called by C++ JNI for dev logging (like FPS)
        public void onDevLog(String msg) {
            activity.appendLog(activity.devLogs, msg);
        }

        // Called by C++ JNI when a scene description is triggered
        public void onSceneTriggered(String base64Image) {
            activity.requestSceneDescription(base64Image);
        }
    }
    
    interface SpeakCallback { void speak(String text); }
}
