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
    private Button btnVision, btnLogsToggle, btnSettings;
    private TextView logTextView;
    private ScrollView logScrollView;
    private boolean ttsReady = false;
    private boolean isHindi = false;

    // Logging State
    private boolean showingDevLogs = false;
    private final LinkedList<String> normalLogs = new LinkedList<>();
    private final LinkedList<String> devLogs = new LinkedList<>();
    private static final int MAX_LOGS = 50;
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
        btnLogsToggle = findViewById(R.id.btn_logs_toggle);
        btnSettings   = findViewById(R.id.btn_settings);
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
        tts = new TextToSpeech(this, this);

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
            tts.setLanguage(Locale.ENGLISH);
            tts.setSpeechRate(0.85f);
            ttsReady = true;
            appendLog(normalLogs, "System: TTS engine initialized");
            Log.d(TAG, "TTS initialized");
        } else {
            appendLog(normalLogs, "System: TTS initialization failed!");
            Log.e(TAG, "TTS initialization failed");
        }
    }

    public void speak(String text) {
        if (ttsReady && tts != null) tts.speak(text, TextToSpeech.QUEUE_ADD, null, null);
        appendLog(normalLogs, "Voice: " + text);
    }

    public void speakUrgent(String text) {
        if (ttsReady && tts != null) tts.speak(text, TextToSpeech.QUEUE_FLUSH, null, null);
        appendLog(normalLogs, "URGENT: " + text);
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
                String[] models = {"yolov8n.onnx", "midas_v21_small_256.onnx"};
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
        Preview preview = new Preview.Builder().build();
        preview.setSurfaceProvider(cameraPreview.getSurfaceProvider());

        // ImageAnalysis — delivers raw YUV frames to C++ pipeline for AI processing
        ImageAnalysis imageAnalysis = new ImageAnalysis.Builder()
                .setTargetResolution(new Size(320, 240)) // Resolution the AI operates at
                .setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST)
                .setOutputImageFormat(ImageAnalysis.OUTPUT_IMAGE_FORMAT_YUV_420_888)
                .build();

        imageAnalysis.setAnalyzer(cameraExecutor, image -> {
            if (nativePipeline != null && !isSwitchingCamera) {
                byte[] nv21 = yuv420ToNv21(image);
                // Pipeline processes at the image's dimensions, e.g. 320x240
                nativePipeline.processFrame(nv21, image.getWidth(), image.getHeight());
            }
            image.close();
        });

        try {
            activeCamera = cameraProvider.bindToLifecycle(this, selector, preview, imageAnalysis);
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
        String[] options = {"Toggle Language (EN/HI)", "Toggle Dark Mode", "Open Source Licenses"};
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
                } else {
                    Toast.makeText(this,
                        "YOLOv8 (AGPL-3.0)  MiDaS (MIT)  ONNX Runtime (MIT)",
                        Toast.LENGTH_LONG).show();
                }
            }).show();
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

        native void processFrame(byte[] data, int width, int height);

        native void stop();
        native void toggleLanguage();

        // Called by C++ JNI when visual frame is processed
        public void onDetections(float[] boxes) {
            Log.d(TAG, "onDetections received " + (boxes.length / 6) + " boxes");
            // Note: 320x240 is the hardcoded AI pipeline resolution we requested from CameraX
            activity.runOnUiThread(() -> activity.overlayView.setBoundingBoxes(boxes, 320, 240));
        }

        // Called by C++ JNI for dev logging (like FPS)
        public void onDevLog(String msg) {
            activity.appendLog(activity.devLogs, msg);
        }
    }
    
    interface SpeakCallback { void speak(String text); }
}
