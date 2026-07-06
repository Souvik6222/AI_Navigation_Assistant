package com.navigation.assistant;

import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.graphics.RectF;
import android.util.AttributeSet;
import android.util.Log;
import android.view.View;

import androidx.annotation.Nullable;

public class OverlayView extends View {

    private float[] boxes;
    private int previewWidth;
    private int previewHeight;

    private final Paint boxPaint;
    private final Paint textPaint;
    private final Paint bgPaint;

    // Box format: [class_id, x1, y1, x2, y2, distance_m]

    private static final String[] CLASSES = {
        "person","bicycle","car","motorcycle","airplane","bus","train","truck","boat",
        "traffic light","fire hydrant","stop sign","parking meter","bench","bird","cat",
        "dog","horse","sheep","cow","elephant","bear","zebra","giraffe","backpack",
        "umbrella","handbag","tie","suitcase","frisbee","skis","snowboard","sports ball",
        "kite","baseball bat","baseball glove","skateboard","surfboard","tennis racket",
        "bottle","wine glass","cup","fork","knife","spoon","bowl","banana","apple",
        "sandwich","orange","broccoli","carrot","hot dog","pizza","donut","cake","chair",
        "couch","potted plant","bed","dining table","toilet","tv","laptop","mouse",
        "remote","keyboard","cell phone","microwave","oven","toaster","sink","refrigerator",
        "book","clock","vase","scissors","teddy bear","hair drier","toothbrush"
    };

    public OverlayView(Context context, @Nullable AttributeSet attrs) {
        super(context, attrs);
        boxPaint = new Paint();
        boxPaint.setColor(Color.GREEN);
        boxPaint.setStyle(Paint.Style.STROKE);
        boxPaint.setStrokeWidth(5f);

        textPaint = new Paint();
        textPaint.setColor(Color.WHITE);
        textPaint.setTextSize(40f);
        textPaint.setFakeBoldText(true);

        bgPaint = new Paint();
        bgPaint.setColor(0x88000000); // semi-transparent black
        bgPaint.setStyle(Paint.Style.FILL);
    }

    public void setBoundingBoxes(float[] boxes, int previewWidth, int previewHeight) {
        this.boxes = boxes;
        this.previewWidth = previewWidth;
        this.previewHeight = previewHeight;
        postInvalidate(); // trigger redraw on main thread
    }

    @Override
    protected void onDraw(Canvas canvas) {
        super.onDraw(canvas);

        if (boxes == null || boxes.length == 0 || previewWidth == 0 || previewHeight == 0) {
            return;
        }
        
        Log.d("NavAssistant", "OverlayView drawing " + (boxes.length / 6) + " boxes");

        // Scale coordinates from AI resolution (e.g. 320x240) to Screen resolution
        // Note: CameraX PreviewView uses FILL_CENTER, so we need to compute the exact mapping
        // based on the aspect ratios. For simplicity, we assume FILL_CENTER scales to fit the largest dimension 
        // and crops the rest. 
        
        int viewWidth = getWidth();
        int viewHeight = getHeight();

        // Calculate scaling and translation to match PreviewView scaleType="fillCenter"
        float scaleX = (float) viewWidth / previewWidth;
        float scaleY = (float) viewHeight / previewHeight;
        float scale = Math.max(scaleX, scaleY); // fillCenter uses max scale

        float scaledWidth = previewWidth * scale;
        float scaledHeight = previewHeight * scale;

        float offsetX = (viewWidth - scaledWidth) / 2f;
        float offsetY = (viewHeight - scaledHeight) / 2f;

        for (int i = 0; i < boxes.length; i += 6) {
            if (i + 5 >= boxes.length) break;

            int classId = (int) boxes[i];
            float x1 = boxes[i + 1];
            float y1 = boxes[i + 2];
            float x2 = boxes[i + 3];
            float y2 = boxes[i + 4];
            float distance = boxes[i + 5];

            // Scale to screen
            float left = x1 * scale + offsetX;
            float top = y1 * scale + offsetY;
            float right = x2 * scale + offsetX;
            float bottom = y2 * scale + offsetY;

            // Clamp to screen bounds
            left = Math.max(0, Math.min(left, viewWidth));
            top = Math.max(0, Math.min(top, viewHeight));
            right = Math.max(0, Math.min(right, viewWidth));
            bottom = Math.max(0, Math.min(bottom, viewHeight));

            RectF rect = new RectF(left, top, right, bottom);
            
            // Dynamic color based on distance
            if (distance > 0 && distance < 2.0f) {
                boxPaint.setColor(Color.RED); // Urgent
            } else if (distance >= 2.0f && distance < 4.0f) {
                boxPaint.setColor(0xFFFFA500); // Orange - Warning
            } else {
                boxPaint.setColor(Color.GREEN); // Info
            }

            canvas.drawRect(rect, boxPaint);

            String label = (classId >= 0 && classId < CLASSES.length) ? CLASSES[classId] : "Unknown";
            String text = String.format("%s %.1fm", label, distance);

            // Draw text background
            float textWidth = textPaint.measureText(text);
            canvas.drawRect(left, top - 45, left + textWidth + 10, top, bgPaint);
            
            // Draw text
            canvas.drawText(text, left + 5, top - 10, textPaint);
        }
    }
}
