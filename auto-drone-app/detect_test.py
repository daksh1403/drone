"""
Improved Paint Detector — Fix Detection Issues
===============================================
Modes:
  - WHITE = unpainted (default): Detect white areas on colored walls
  - COLORED = unpainted: Detect non-white areas on white walls (REVERSED)

Run: python detect_test.py
"""

import cv2
import numpy as np
import sys
import os


class ImprovedPaintDetector:
    """
    Fixed detection with:
    1. Two detection modes (white vs colored unpainted)
    2. Debug visualization (see each method's output)
    3. Better morphological cleanup
    4. Adaptive threshold tuning
    """

    def __init__(self):
        self.clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))

    def detect(self, frame, sensitivity=50, mode='white'):
        """
        Detect unpainted areas.

        Args:
            frame: BGR image
            sensitivity: 0-100 (higher = more aggressive)
            mode: 'white' = white is unpainted (colored wall)
                  'colored' = colored/dark is unpainted (white wall)
        Returns:
            dict with regions, combined_mask, debug_masks
        """
        h, w = frame.shape[:2]
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        gray_enhanced = self.clahe.apply(gray)
        lab = cv2.cvtColor(frame, cv2.COLOR_BGR2LAB)
        l_enhanced = self.clahe.apply(lab[:, :, 0])
        s_channel = hsv[:, :, 1]
        v_channel = hsv[:, :, 2]

        debug = {}

        # --- Method 1: Adaptive threshold ---
        adaptive_mask = cv2.adaptiveThreshold(
            gray_enhanced, 255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY,
            blockSize=51,
            C=-5 - (sensitivity // 10)
        )
        debug['adaptive'] = adaptive_mask.copy()

        # --- Method 2: Relative brightness ---
        mean_brightness = gray.mean()
        threshold = max(50, mean_brightness - 20 + (sensitivity // 2))
        _, relative_mask = cv2.threshold(gray, int(threshold), 255, cv2.THRESH_BINARY)
        debug['relative'] = relative_mask.copy()

        # --- Method 3: Saturation check ---
        max_saturation = 40 + sensitivity
        min_brightness = max(30, 80 - sensitivity)
        low_sat = (s_channel < max_saturation).astype(np.uint8) * 255
        not_dark = (v_channel > min_brightness).astype(np.uint8) * 255
        saturation_mask = cv2.bitwise_and(low_sat, not_dark)
        debug['saturation'] = saturation_mask.copy()

        # --- Method 4: Otsu ---
        _, otsu_mask = cv2.threshold(gray_enhanced, 0, 255,
                                      cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        debug['otsu'] = otsu_mask.copy()

        # --- Method 5: LAB L-channel ---
        l_mean = l_enhanced.mean()
        l_threshold = max(80, l_mean - 10 + (sensitivity // 3))
        _, lab_mask = cv2.threshold(l_enhanced, int(l_threshold), 255,
                                     cv2.THRESH_BINARY)
        debug['lab'] = lab_mask.copy()

        # --- Method 6: Blurred threshold ---
        blurred = cv2.GaussianBlur(gray, (21, 21), 0)
        blur_threshold = max(40, blurred.mean() - 15 + (sensitivity // 2))
        _, blur_mask = cv2.threshold(blurred, int(blur_threshold), 255,
                                      cv2.THRESH_BINARY)
        debug['blur'] = blur_mask.copy()

        # --- Weighted combination ---
        combined = np.zeros_like(gray, dtype=np.float32)
        combined += adaptive_mask.astype(np.float32) * 0.30
        combined += relative_mask.astype(np.float32) * 0.20
        combined += saturation_mask.astype(np.float32) * 0.25
        combined += otsu_mask.astype(np.float32) * 0.10
        combined += lab_mask.astype(np.float32) * 0.10
        combined += blur_mask.astype(np.float32) * 0.05
        combined = np.clip(combined, 0, 255).astype(np.uint8)
        _, combined_mask = cv2.threshold(combined, 100, 255, cv2.THRESH_BINARY)

        # --- MODE SWITCHING ---
        # If mode is 'colored', INVERT the mask (non-white = unpainted)
        if mode == 'colored':
            combined_mask = cv2.bitwise_not(combined_mask)
            debug['mode_note'] = 'INVERTED: non-white areas are unpainted'
        else:
            debug['mode_note'] = 'NORMAL: white areas are unpainted'

        # --- Better morphological cleanup ---
        kernel_small = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
        kernel_medium = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
        kernel_large = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (11, 11))

        # Remove noise (small white specks)
        combined_mask = cv2.morphologyEx(combined_mask, cv2.MORPH_OPEN, kernel_small)
        # Fill small holes
        combined_mask = cv2.morphologyEx(combined_mask, cv2.MORPH_CLOSE, kernel_medium)
        # Smooth edges
        combined_mask = cv2.morphologyEx(combined_mask, cv2.MORPH_OPEN, kernel_large)

        debug['final'] = combined_mask.copy()

        # --- Extract regions ---
        regions = []
        contours, _ = cv2.findContours(combined_mask, cv2.RETR_EXTERNAL,
                                        cv2.CHAIN_APPROX_SIMPLE)
        min_area = (w * h) * 0.005

        for contour in contours:
            area = cv2.contourArea(contour)
            if area < min_area:
                continue
            x, y, rw, rh = cv2.boundingRect(contour)
            hull = cv2.convexHull(contour)
            hull_area = cv2.contourArea(hull)
            solidity = area / hull_area if hull_area > 0 else 0
            roi_gray = gray[y:y + rh, x:x + rw]
            roi_sat = s_channel[y:y + rh, x:x + rw]

            size_score = min(1.0, area / (w * h * 0.1))
            sat_score = 1.0 - (roi_sat.mean() / 255)
            uniform_score = 1.0 - min(1.0, roi_gray.std() / 50)
            confidence = (size_score * 0.25 + solidity * 0.25 +
                          sat_score * 0.30 + uniform_score * 0.20)

            regions.append({
                'box': (x, y, rw, rh),
                'center': (x + rw // 2, y + rh // 2),
                'confidence': confidence,
                'contour': contour
            })

        regions.sort(key=lambda r: r['confidence'], reverse=True)
        return {'regions': regions, 'combined_mask': combined_mask, 'debug': debug}


def build_grid(mask, rows=8, cols=12, threshold=0.3):
    """Build grid with adjustable threshold (lower = more sensitive)."""
    h, w = mask.shape[:2]
    cell_h = max(1, h // rows)
    cell_w = max(1, w // cols)

    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    clean = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    clean = cv2.morphologyEx(clean, cv2.MORPH_CLOSE, kernel)

    grid = []
    for r in range(rows):
        row = []
        for c in range(cols):
            x0, y0 = c * cell_w, r * cell_h
            x1 = w if c == cols - 1 else (c + 1) * cell_w
            y1 = h if r == rows - 1 else (r + 1) * cell_h
            cell = clean[y0:y1, x0:x1]
            if cell.size == 0:
                row.append(False)
                continue
            filled = float(np.count_nonzero(cell)) / float(cell.size)
            row.append(filled >= threshold)
        grid.append(row)
    return grid


def draw_debug_view(frame, debug, regions):
    """Create a debug visualization showing each method's output."""
    h, w = frame.shape[:2]
    small_h, small_w = h // 3, w // 3

    # Create 2x3 grid of debug images
    methods = ['adaptive', 'relative', 'saturation', 'otsu', 'lab', 'blur']
    labels = ['Adaptive', 'Relative', 'Saturation', 'Otsu', 'LAB L', 'Blur']

    panels = []
    for i, (method, label) in enumerate(zip(methods, labels)):
        mask = debug.get(method, np.zeros((h, w), dtype=np.uint8))
        # Convert mask to BGR for display
        panel = cv2.cvtColor(mask, cv2.COLOR_GRAY2BGR)
        panel = cv2.resize(panel, (small_w, small_h))
        # Add label
        cv2.putText(panel, label, (5, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
        panels.append(panel)

    # Add final combined mask
    final = debug.get('final', np.zeros((h, w), dtype=np.uint8))
    final_bgr = cv2.cvtColor(final, cv2.COLOR_GRAY2BGR)
    final_bgr = cv2.resize(final_bgr, (small_w, small_h))
    cv2.putText(final_bgr, 'FINAL', (5, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
    panels.append(final_bgr)

    # Add original with detections
    orig = frame.copy()
    for reg in regions:
        x, y, rw, rh = reg['box']
        cv2.rectangle(orig, (x, y), (x + rw, y + rh), (0, 255, 0), 2)
        cx, cy = reg['center']
        cv2.circle(orig, (cx, cy), 5, (0, 0, 255), -1)
    orig_small = cv2.resize(orig, (small_w, small_h))
    cv2.putText(orig_small, 'DETECTIONS', (5, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 0), 2)
    panels.append(orig_small)

    # Arrange in 2 rows of 4
    top_row = np.hstack(panels[:4])
    bottom_row = np.hstack(panels[4:])

    # Pad if needed
    if top_row.shape[1] != bottom_row.shape[1]:
        diff = abs(top_row.shape[1] - bottom_row.shape[1])
        if top_row.shape[1] < bottom_row.shape[1]:
            top_row = cv2.copyMakeBorder(top_row, 0, 0, 0, diff, cv2.BORDER_CONSTANT)
        else:
            bottom_row = cv2.copyMakeBorder(bottom_row, 0, 0, 0, diff, cv2.BORDER_CONSTANT)

    debug_view = np.vstack([top_row, bottom_row])
    return debug_view


def main():
    # Parse arguments
    mode = 'white'
    sensitivity = 50
    source = 0  # Default webcam

    if len(sys.argv) > 1:
        if sys.argv[1] == '--colored':
            mode = 'colored'
            print("MODE: COLORED = unpainted (detect non-white areas on white walls)")
        elif sys.argv[1] == '--white':
            mode = 'white'
            print("MODE: WHITE = unpainted (detect white areas on colored walls)")
        elif sys.argv[1].isdigit():
            source = int(sys.argv[1])
        else:
            # Try as image file
            if os.path.exists(sys.argv[1]):
                source = sys.argv[1]

    if len(sys.argv) > 2:
        sensitivity = int(sys.argv[2])

    print(f"Sensitivity: {sensitivity}")
    print(f"Source: {source}")
    print()
    print("CONTROLS:")
    print("  [+/-]  Adjust sensitivity")
    print("  [M]    Toggle mode (white/colored)")
    print("  [D]    Toggle debug view")
    print("  [SPACE] Capture snapshot")
    print("  [Q]    Quit")
    print()

    detector = ImprovedPaintDetector()

    # Open source
    if isinstance(source, str) and source.isdigit():
        cap = cv2.VideoCapture(int(source))
    elif isinstance(source, int):
        cap = cv2.VideoCapture(source)
    else:
        cap = cv2.VideoCapture(source)

    if not cap.isOpened():
        print(f"ERROR: Cannot open source '{source}'")
        return

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)

    show_debug = False
    snapshot = None

    while True:
        if snapshot is not None:
            frame = snapshot.copy()
        else:
            ret, frame = cap.read()
            if not ret:
                break

        # Run detection
        result = detector.detect(frame, sensitivity, mode)
        regions = result['regions']
        mask = result['combined_mask']
        debug = result['debug']

        # Build grid
        grid = build_grid(mask, threshold=0.3)
        cell_count = sum(cell for row in grid for cell in row)

        # Draw main view
        display = frame.copy()
        for reg in regions:
            x, y, rw, rh = reg['box']
            conf = reg['confidence']
            color = (0, int(255 * conf), 0)
            cv2.rectangle(display, (x, y), (x + rw, y + rh), color, 2)
            cx, cy = reg['center']
            cv2.circle(display, (cx, cy), 5, (0, 255, 255), -1)

        # Info panel
        cv2.rectangle(display, (10, 10), (350, 100), (0, 0, 0), -1)
        mode_text = "MODE: COLORED=unpainted" if mode == 'colored' else "MODE: WHITE=unpainted"
        cv2.putText(display, f"Sensitivity: {sensitivity} [+/-]", (20, 35),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 0), 2)
        cv2.putText(display, mode_text, (20, 60),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1)
        cv2.putText(display, f"Regions: {len(regions)} | Grid cells: {cell_count}/96", (20, 85),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)

        cv2.imshow('Detection', display)
        cv2.imshow('Mask', mask)

        if show_debug:
            debug_view = draw_debug_view(frame, debug, regions)
            cv2.imshow('Debug (Each Method)', debug_view)

        # Handle keys
        key = cv2.waitKey(1) & 0xFF

        if key == ord('q'):
            break
        elif key == ord('+') or key == ord('='):
            sensitivity = min(100, sensitivity + 5)
            print(f"Sensitivity: {sensitivity}")
        elif key == ord('-') or key == ord('_'):
            sensitivity = max(0, sensitivity - 5)
            print(f"Sensitivity: {sensitivity}")
        elif key == ord('m'):
            mode = 'colored' if mode == 'white' else 'white'
            print(f"Mode: {mode}")
        elif key == ord('d'):
            show_debug = not show_debug
            if not show_debug:
                cv2.destroyWindow('Debug (Each Method)')
            print(f"Debug view: {'ON' if show_debug else 'OFF'}")
        elif key == ord(' '):
            snapshot = frame.copy()
            print(f"\n--- CAPTURED ---")
            print(f"Sensitivity: {sensitivity}")
            print(f"Mode: {mode}")
            print(f"Regions found: {len(regions)}")
            for i, r in enumerate(regions):
                print(f"  Region {i+1}: box={r['box']}, conf={r['confidence']:.2f}")
            print(f"Grid cells: {cell_count}/96")
            print(f"----------------\n")

    cap.release()
    cv2.destroyAllWindows()


if __name__ == '__main__':
    main()
