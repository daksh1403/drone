"""Flask Backend — Autonomous Painting System"""
import cv2
import numpy as np
import base64, time, json, threading, queue
from flask import Flask, Response, request, jsonify, send_from_directory
from flask_cors import CORS

app = Flask(__name__, static_folder="static")
CORS(app)

GRID_ROWS, GRID_COLS = 8, 12

# ══════════════════════════════════════════════════════════════
# CAMERA — single persistent thread, all endpoints read from it
# ══════════════════════════════════════════════════════════════

class Camera:
    def __init__(self):
        self.frame = None
        self.lock = threading.Lock()
        self.running = False

    def start(self):
        self.running = True
        threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self):
        cam = cv2.VideoCapture(0, cv2.CAP_DSHOW)
        if not cam.isOpened():
            cam = cv2.VideoCapture(0)
        cam.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        cam.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        print("[CAM] Opened")
        while self.running:
            ret, frame = cam.read()
            if ret:
                with self.lock:
                    self.frame = frame
            time.sleep(0.01)
        cam.release()
        print("[CAM] Closed")

    def read(self):
        with self.lock:
            return self.frame.copy() if self.frame is not None else None

cam = Camera()

# ══════════════════════════════════════════════════════════════
# DETECTOR
# ══════════════════════════════════════════════════════════════

class PaintDetector:
    def __init__(self):
        self.clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))

    def detect(self, frame, sens=50):
        g = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        ge = self.clahe.apply(g)
        le = self.clahe.apply(cv2.cvtColor(frame, cv2.COLOR_BGR2LAB)[:,:,0])
        s, v = hsv[:,:,1], hsv[:,:,2]
        a = cv2.adaptiveThreshold(ge, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 51, -5-(sens//10))
        _, r = cv2.threshold(g, int(max(50, g.mean()-20+sens//2)), 255, cv2.THRESH_BINARY)
        m = cv2.bitwise_and((s<40+sens).astype(np.uint8)*255, (v>max(30,80-sens)).astype(np.uint8)*255)
        _, o = cv2.threshold(ge, 0, 255, cv2.THRESH_BINARY+cv2.THRESH_OTSU)
        _, l = cv2.threshold(le, int(max(80, le.mean()-10+sens//3)), 255, cv2.THRESH_BINARY)
        bl = cv2.GaussianBlur(g,(21,21),0)
        _, b = cv2.threshold(bl, int(max(40, bl.mean()-15+sens//2)), 255, cv2.THRESH_BINARY)
        c = (a*0.30+r*0.20+m*0.25+o*0.10+l*0.10+b*0.05).astype(np.uint8)
        _, mask = cv2.threshold(c, 100, 255, cv2.THRESH_BINARY)
        k1 = cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(3,3))
        k2 = cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(7,7))
        return cv2.morphologyEx(cv2.morphologyEx(mask, cv2.MORPH_OPEN, k1), cv2.MORPH_CLOSE, k2)

    def methods(self, frame, sens=50):
        g = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        ge = self.clahe.apply(g)
        le = self.clahe.apply(cv2.cvtColor(frame, cv2.COLOR_BGR2LAB)[:,:,0])
        s, v = hsv[:,:,1], hsv[:,:,2]
        a = cv2.adaptiveThreshold(ge, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 51, -5-(sens//10))
        _, r = cv2.threshold(g, int(max(50, g.mean()-20+sens//2)), 255, cv2.THRESH_BINARY)
        m = cv2.bitwise_and((s<40+sens).astype(np.uint8)*255, (v>max(30,80-sens)).astype(np.uint8)*255)
        _, o = cv2.threshold(ge, 0, 255, cv2.THRESH_BINARY+cv2.THRESH_OTSU)
        _, l = cv2.threshold(le, int(max(80, le.mean()-10+sens//3)), 255, cv2.THRESH_BINARY)
        bl = cv2.GaussianBlur(g,(21,21),0)
        _, b = cv2.threshold(bl, int(max(40, bl.mean()-15+sens//2)), 255, cv2.THRESH_BINARY)
        c = (a*0.30+r*0.20+m*0.25+o*0.10+l*0.10+b*0.05).astype(np.uint8)
        _, f = cv2.threshold(c, 100, 255, cv2.THRESH_BINARY)
        k1 = cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(3,3))
        k2 = cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(7,7))
        f = cv2.morphologyEx(cv2.morphologyEx(f, cv2.MORPH_OPEN, k1), cv2.MORPH_CLOSE, k2)
        return [a,r,m,o,l,b,f]

det = PaintDetector()

def build_grid(mask, thr=0.4):
    h, w = mask.shape[:2]
    ch, cw = h//GRID_ROWS, w//GRID_COLS
    return [[float(np.count_nonzero(mask[r*ch:(r+1)*ch, c*cw:(c+1)*cw]))/float(max(1,mask[r*ch:(r+1)*ch, c*cw:(c+1)*cw].size))>=thr for c in range(GRID_COLS)] for r in range(GRID_ROWS)]

def draw_grid(frame, grid, sens):
    h, w = frame.shape[:2]
    ch, cw = h//GRID_ROWS, w//GRID_COLS
    ov = frame.copy()
    idx = 1
    for r in range(GRID_ROWS):
        for c in range(GRID_COLS):
            x0,y0 = c*cw, r*ch
            x1 = w if c==GRID_COLS-1 else (c+1)*cw
            y1 = h if r==GRID_ROWS-1 else (r+1)*ch
            if grid[r][c]:
                cv2.rectangle(ov,(x0+1,y0+1),(x1-1,y1-1),(0,200,0),-1)
                cv2.rectangle(ov,(x0,y0),(x1,y1),(0,255,0),1)
                cv2.putText(ov,str(idx),(x0+cw//2-6,y0+ch//2+5),cv2.FONT_HERSHEY_SIMPLEX,0.45,(255,255,255),2)
                cv2.putText(ov,str(idx),(x0+cw//2-6,y0+ch//2+5),cv2.FONT_HERSHEY_SIMPLEX,0.45,(0,0,0),1)
                idx+=1
            else:
                cv2.rectangle(ov,(x0+1,y0+1),(x1-1,y1-1),(0,0,0),-1)
                cv2.rectangle(ov,(x0,y0),(x1,y1),(60,60,60),1)
    res = cv2.addWeighted(ov,0.4,frame,0.6,0)
    cc = sum(cell for row in grid for cell in row)
    cv2.rectangle(res,(10,10),(380,50),(0,0,0),-1)
    cv2.putText(res,f"LIVE | Sens: {sens} | White: {cc}/96",(15,35),cv2.FONT_HERSHEY_SIMPLEX,0.5,(0,255,0),2)
    return res

def to_jpeg(frame):
    _, j = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
    return j.tobytes()

def stream_response(gen):
    def g():
        for f in gen:
            if f is None: continue
            d = to_jpeg(f)
            yield b'--frame\r\nContent-Type: image/jpeg\r\nContent-Length: '+str(len(d)).encode()+b'\r\n\r\n'+d+b'\r\n'
    return Response(g(), mimetype='multipart/x-mixed-replace; boundary=frame',
                    headers={'Cache-Control':'no-cache','X-Accel-Buffering':'no','Access-Control-Allow-Origin':'*'})

@app.route("/")
def index():
    return send_from_directory("static", "index.html")

@app.route("/ping")
def ping():
    return jsonify({"status":"ok"})

@app.route("/video_feed")
def video_feed():
    def gen():
        while True:
            f = cam.read()
            if f is None:
                time.sleep(0.05)
                continue
            yield f
    return stream_response(gen())

@app.route("/live_detect")
def live_detect():
    s = request.args.get("sensitivity", 50, type=int)
    def gen():
        while True:
            f = cam.read()
            if f is None: continue
            yield draw_grid(f, build_grid(det.detect(f, s)), s)
    return stream_response(gen())

@app.route("/debug_methods")
def debug_methods():
    s = request.args.get("sensitivity", 50, type=int)
    labels = ["Adaptive","Relative","Saturation","Otsu","LAB","Blur","FINAL"]
    def gen():
        while True:
            f = cam.read()
            if f is None: continue
            ms = det.methods(f, s)
            h, w = f.shape[:2]
            sw, sh = w//3, h//3
            ps = []
            for m, l in zip(ms, labels):
                p = cv2.cvtColor(m, cv2.COLOR_GRAY2BGR)
                p = cv2.resize(p,(sw,sh))
                cv2.putText(p,l,(5,20),cv2.FONT_HERSHEY_SIMPLEX,0.5,(0,255,0),2)
                ps.append(p)
            o = cv2.resize(f,(sw,sh))
            cv2.putText(o,"ORIGINAL",(5,20),cv2.FONT_HERSHEY_SIMPLEX,0.5,(255,255,0),2)
            ps.append(o)
            yield np.vstack([np.hstack(ps[:4]), np.hstack(ps[4:])])
    return stream_response(gen())

@app.route("/capture", methods=["POST"])
def capture():
    f = cam.read()
    if f is None: return jsonify({"error":"No camera"}), 500
    s = request.args.get("sensitivity", 50, type=int)
    mask = det.detect(f, s)
    grid = build_grid(mask)
    _, j = cv2.imencode(".jpg", f, [cv2.IMWRITE_JPEG_QUALITY, 90])
    return jsonify({"image": base64.b64encode(j.tobytes()).decode(), "grid": grid,
                    "cell_count": sum(cell for row in grid for cell in row)})

@app.route("/spray_sequence", methods=["POST"])
def spray_sequence():
    cells = request.get_json(force=True).get("cells", [])
    def gen():
        n = len(cells)
        for i,(row,col) in enumerate(cells):
            yield f"data: {json.dumps({'status':'moving','cell':i+1,'total':n,'row':row,'col':col})}\n\n"
            time.sleep(3)
            yield f"data: {json.dumps({'status':'spraying','cell':i+1})}\n\n"
            time.sleep(1)
            yield f"data: {json.dumps({'status':'done','cell':i+1})}\n\n"
        yield f"data: {json.dumps({'status':'complete','total':n})}\n\n"
    return Response(gen(), mimetype="text/event-stream",
                    headers={"Cache-Control":"no-cache","Access-Control-Allow-Origin":"*"})

if __name__ == "__main__":
    print("Open http://localhost:5000")
    cam.start()
    time.sleep(2)
    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)
