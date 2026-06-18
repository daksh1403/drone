"""
Live Detection View — Grid overlay on camera feed
==================================================
Shows the 8×12 grid ON TOP of the live camera so you can see
exactly what the model detects as white/unpainted.

Run: python live_detect.py
Controls:
  [+/-]  Adjust sensitivity
  [G]    Toggle grid overlay
  [S]    Toggle mask view
  [SPACE] Freeze frame
  [Q]    Quit
"""

import cv2
import numpy as np


class LiveDetector:
    def __init__(self):
        self.clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))

    def detect(self, frame, sensitivity=50):
        h, w = frame.shape[:2]
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        gray_enhanced = self.clahe.apply(gray)
        lab = cv2.cvtColor(frame, cv2.COLOR_BGR2LAB)
        l_enhanced = self.clahe.apply(lab[:, :, 0])
        s_channel = hsv[:, :, 1]
        v_channel = hsv[:, :, 2]

        # Method 1: Adaptive
        adaptive = cv2.adaptiveThreshold(
            gray_enhanced, 255, cv2.ADAPTIVE_THRESH_GaussIAN_C if hasattr(cv2, 'ADAPTIVE_THRESH_GaussIAN_C') else cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY, blockSize=51, C=-5 - (sensitivity // 10))

        # Method 2: Relative brightness
        mean_b = gray.mean()
        _, relative = cv2.threshold(gray, int(max(50, mean_b - 20 + sensitivity // 2)), 255, cv2.THRESH_BINARY)

        # Method 3: Saturation
        low_sat = (s_channel < 40 + sensitivity).astype(np.uint8) * 255
        not_dark = (v_channel > max(30, 80 - sensitivity)).astype(np.uint8) * 255
        saturation = cv2.bitwise_and(low_sat, not_dark)

        # Method 4: Otsu
        _, otsu = cv2.threshold(gray_enhanced, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

        # Method 5: LAB
        l_mean = l_enhanced.mean()
        _, lab_mask = cv2.threshold(l_enhanced, int(max(80, l_mean - 10 + sensitivity // 3)), 255, cv2.THRESH_BINARY)

        # Method 6: Blur
        blurred = cv2.GaussianBlur(gray, (21, 21), 0)
        _, blur_mask = cv2.threshold(blurred, int(max(40, blurred.mean() - 15 + sensitivity // 2)), 255, cv2.THRESH_BINARY)

        # Combine
        combined = (adaptive.astype(np.float32) * 0.30 +
                    relative.astype(np.float32) * 0.20 +
                    saturation.astype(np.float32) * 0.25 +
                    otsu.astype(np.float32) * 0.10 +
                    lab_mask.astype(np.float32) * 0.10 +
                    blur_mask.astype(np.float32) * 0.05)
        combined = np.clip(combined, 0, 255).astype(np.uint8)
        _, mask = cv2.threshold(combined, 100, 255, cv2.THRESH_BINARY)

        # Cleanup
        k1 = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
        k2 = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, k1)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, k2)

        return mask


def build_grid_from_mask(mask, rows=8, cols=12, threshold=0.3):
    """Build grid from detection mask."""
    h, w = mask.shape[:2]
    cell_h = h // rows
    cell_w = w // cols
    grid = []
    for r in range(rows):
        row = []
        for c in range(cols):
            x0, y0 = c * cell_w, r * cell_h
            x1 = w if c == cols - 1 else (c + 1) * cell_w
            y1 = h if r == rows - 1 else (r + 1) * cell_h
            cell = mask[y0:y1, x0:x1]
            filled = float(np.count_nonzero(cell)) / float(cell.size) if cell.size > 0 else 0
            row.append(filled >= threshold)
        grid.append(row)
    return grid


def draw_grid_overlay(frame, grid, rows=8, cols=12):
    """Draw grid overlay on frame. Green = detected white, Red = not detected."""
    overlay = frame.copy()
    h, w = overlay.shape[:2]
    cell_h = h // rows
    cell_w = w // cols

    for r in range(rows):
        for c in range(cols):
            x0, y0 = c * cell_w, r * cell_h
            x1 = w if c == cols - 1 else (c + 1) * cell_w
            y1 = h if r == rows - 1 else (r + 1) * cell_h

            if grid[r][c]:
                # WHITE detected = green overlay
                cv2.rectangle(overlay, (x0 + 1, y0 + 1), (x1 - 1, y1 - 1), (0, 200, 0), -1)
                cv2.rectangle(overlay, (x0, y0), (x1, y1), (0, 255, 0), 1)
            else:
                # Not detected = dark overlay
                cv2.rectangle(overlay, (x0 + 1, y0 + 1), (x1 - 1, y1 - 1), (0, 0, 0), -1)
                cv2.rectangle(overlay, (x0, y0), (x1, y1), (80, 80, 80), 1)

    # Blend
    result = cv2.addWeighted(overlay, 0.4, frame, 0.6, 0)

    # Cell numbers
    idx = 1
    for r in range(rows):
        for c in range(cols):
            if grid[r][c]:
                cx = c * cell_w + cell_w // 2
                cy = r * cell_h + cell_h // 2
                cv2.putText(result, str(idx), (cx - 6, cy + 5),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 2)
                cv2.putText(result, str(idx), (cx - 6, cy + 5),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1)
                idx += 1

    return result


def main():
    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        print("ERROR: Cannot open camera")
        return

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)

    detector = LiveDetector()
    sensitivity = 50
    show_grid = True
    show_mask = False
    frozen = None

    print("LIVE DETECTION VIEW")
    print("=" * 40)
    print("[+/-]  Sensitivity")
    print("[G]    Toggle grid")
    print("[S]    Toggle mask")
    print("[SPACE] Freeze frame")
    print("[Q]    Quit")
    print("=" * 40)

    while True:
        if frozen is not None:
            frame = frozen.copy()
        else:
            ret, frame = cap.read()
            if not ret:
                break

        # Detect
        mask = detector.detect(frame, sensitivity)
        grid = build_grid_from_mask(mask)
        cell_count = sum(cell for row in grid for cell in row)

        # Main view with grid overlay
        if show_grid:
            display = draw_grid_overlay(frame, grid)
        else:
            display = frame.copy()

        # Info panel
        cv2.rectangle(display, (10, 10), (320, 85), (0, 0, 0), -1)
        cv2.putText(display, f"Sensitivity: {sensitivity} [+/-]", (20, 35),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 0), 2)
        cv2.putText(display, f"White cells detected: {cell_count}/96", (20, 60),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
        mode_text = "FROZEN" if frozen is not None else "LIVE"
        cv2.putText(display, f"[{mode_text}] Grid: {'ON' if show_grid else 'OFF'}", (20, 80),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, (200, 200, 200), 1)

        cv2.imshow('Live Detection', display)

        if show_mask:
            mask_bgr = cv2.cvtColor(mask, cv2.COLOR_GRAY2BGR)
            cv2.imshow('Detection Mask', mask_bgr)

        key = cv2.waitKey(1) & 0xFF

        if key == ord('q'):
            break
        elif key == ord('+') or key == ord('='):
            sensitivity = min(100, sensitivity + 5)
            print(f"Sensitivity: {sensitivity}")
        elif key == ord('-') or key == ord('_'):
            sensitivity = max(0, sensitivity - 5)
            print(f"Sensitivity: {sensitivity}")
        elif key == ord('g'):
            show_grid = not show_grid
            print(f"Grid: {'ON' if show_grid else 'OFF'}")
        elif key == ord('s'):
            show_mask = not show_mask
            if not show_mask:
                cv2.destroyWindow('Detection Mask')
            print(f"Mask view: {'ON' if show_mask else 'OFF'}")
        elif key == ord(' '):
            if frozen is None:
                frozen = frame.copy()
                print("FROZEN — press SPACE to unfreeze")
            else:
                frozen = None
                print("UNFROZEN")

    cap.release()
    cv2.destroyAllWindows()


if __name__ == '__main__':
    main()
