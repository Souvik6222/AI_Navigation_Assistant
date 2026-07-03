package com.navigation.assistant;

import android.Manifest;
import android.content.pm.PackageManager;
import android.os.Bundle;
import android.speech.tts.TextToSpeech;
import android.util.Log;
import android.view.SurfaceView;
import android.widget.Toast;

import androidx.annotation.NonNull;
import androidx.appcompat.app.AppCompatActivity;
import androidx.core.app.ActivityCompat;
import androidx.core.content.ContextCompat;

import java.util.Locale;

public class MainActivity extends AppCompatActivity implements TextToSpeech.OnInitListener {

    private static final String TAG = "NavAssistant";
    private static final int CAMERA_PERMISSION_CODE = 100;

    private TextToSpeech tts;
    private NativePipeline nativePipeline;
    private SurfaceView cameraPreview;
    private boolean ttsReady = false;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_main);

        cameraPreview = findViewById(R.id.camera_preview);

        // Initialize TTS
        tts = new TextToSpeech(this, this);

        // Check camera permission
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.CAMERA)
                != PackageManager.PERMISSION_GRANTED) {
            ActivityCompat.requestPermissions(this,
                    new String[]{Manifest.permission.CAMERA}, CAMERA_PERMISSION_CODE);
        } else {
            startPipeline();
        }
    }

    @Override
    public void onInit(int status) {
        if (status == TextToSpeech.SUCCESS) {
            tts.setLanguage(Locale.ENGLISH);
            tts.setSpeechRate(0.85f);
            ttsReady = true;
            Log.d(TAG, "TTS initialized");
        } else {
            Log.e(TAG, "TTS initialization failed");
        }
    }

    public void speak(String text) {
        if (ttsReady && tts != null) {
            tts.speak(text, TextToSpeech.QUEUE_ADD, null, null);
        }
    }

    public void speakUrgent(String text) {
        if (ttsReady && tts != null) {
            tts.speak(text, TextToSpeech.QUEUE_FLUSH, null, null);
        }
    }

    private void startPipeline() {
        nativePipeline = new NativePipeline();
        nativePipeline.start(
            getAssets(),
            cameraPreview.getHolder().getSurface(),
            this::speak,
            this::speakUrgent
        );
        Log.d(TAG, "Native pipeline started");
    }

    @Override
    public void onRequestPermissionsResult(int requestCode,
                                           @NonNull String[] permissions,
                                           @NonNull int[] grantResults) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults);
        if (requestCode == CAMERA_PERMISSION_CODE) {
            if (grantResults.length > 0 && grantResults[0] == PackageManager.PERMISSION_GRANTED) {
                startPipeline();
            } else {
                Toast.makeText(this, "Camera permission required", Toast.LENGTH_LONG).show();
                finish();
            }
        }
    }

    @Override
    protected void onDestroy() {
        if (nativePipeline != null) {
            nativePipeline.stop();
        }
        if (tts != null) {
            tts.stop();
            tts.shutdown();
        }
        super.onDestroy();
    }

    // JNI native methods
    static {
        System.loadLibrary("ai_navigation_assistant");
    }

    private static class NativePipeline {
        native void start(android.content.res.AssetManager assets,
                          android.view.Surface surface,
                          SpeakCallback speakCb,
                          SpeakCallback urgentCb);
        native void stop();

        interface SpeakCallback {
            void speak(String text);
        }
    }
}
