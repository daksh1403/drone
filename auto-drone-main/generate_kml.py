"""Generate KML/KMZ wall overlay for Mission Planner."""
import cv2
import numpy as np
import zipfile

# Create a wall image - aerial footprint
W, H = 800, 400
img = np.full((H, W, 3), 230, dtype=np.uint8)

# Concrete texture
rng = np.random.default_rng(42)
noise = rng.integers(-8, 9, size=(H, W, 3), dtype=np.int16)
img = np.clip(img.astype(np.int16) + noise, 0, 255).astype(np.uint8)

ROWS, COLS = 8, 12
cell_h = H // ROWS
cell_w = W // COLS

# Draw grid
for r in range(ROWS + 1):
    y = r * cell_h
    cv2.line(img, (0, y), (W, y), (160, 160, 160), 2)
for c in range(COLS + 1):
    x = c * cell_w
    cv2.line(img, (x, 0), (x, H), (160, 160, 160), 2)

# Painted cells (teal)
painted = [
    (0,0),(0,1),(0,2),(1,0),(1,1),(2,0),(2,1),(2,2),(2,3),
    (3,0),(3,1),(3,2),(3,3),(3,4),(4,0),(4,1),(4,2),(4,3),(4,4),(4,5),
]
for r, c in painted:
    x1, y1 = c * cell_w + 2, r * cell_h + 2
    x2, y2 = (c + 1) * cell_w - 2, (r + 1) * cell_h - 2
    cv2.rectangle(img, (x1, y1), (x2, y2), (180, 120, 50), -1)

# Unpainted cells (white/bare)
unpainted = [
    (0,3),(0,4),(1,2),(1,3),(1,4),(5,0),(5,1),(5,2),
    (6,0),(6,1),(6,2),(6,3),(7,0),(7,1),(7,2),(7,3),(7,4),
]
for r, c in unpainted:
    x1, y1 = c * cell_w + 2, r * cell_h + 2
    x2, y2 = (c + 1) * cell_w - 2, (r + 1) * cell_h - 2
    cv2.rectangle(img, (x1, y1), (x2, y2), (255, 255, 255), -1)

# Cell labels
for r in range(ROWS):
    for c in range(COLS):
        label = "%d,%d" % (r, c)
        tx = c * cell_w + 5
        ty = r * cell_h + cell_h // 2 + 4
        cv2.putText(img, label, (tx, ty), cv2.FONT_HERSHEY_SIMPLEX, 0.3, (120, 120, 120), 1)

# Border + title
cv2.rectangle(img, (0, 0), (W - 1, H - 1), (80, 80, 80), 3)
cv2.putText(img, "WALL - Drone Painting Area", (W // 2 - 150, H - 10),
            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (60, 60, 60), 2)

# Drone path arrow
cv2.arrowedLine(img, (20, 15), (W - 20, 15), (0, 0, 200), 2, tipLength=0.02)
cv2.putText(img, "Drone path >>>", (30, 12), cv2.FONT_HERSHEY_SIMPLEX, 0.35, (0, 0, 200), 1)

# Altitude labels on right side
for r in range(ROWS):
    alt = 3.0 + r * 0.3
    cv2.putText(img, "%.1fm" % alt, (W - 50, r * cell_h + cell_h // 2 + 4),
                cv2.FONT_HERSHEY_SIMPLEX, 0.3, (0, 0, 180), 1)

cv2.imwrite("wall_overlay.png", img)
print("Created wall_overlay.png (%dx%d)" % (W, H))

# KML — overlay centered on SITL home
lat_center = 13.0827
lon_center = 80.2707
half_w = 0.000165   # ~18m longitude
half_h = 0.000085   # ~9.5m latitude

kml_text = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<kml xmlns="http://www.opengis.net/kml/2.2">\n'
    "  <Document>\n"
    "    <name>Wall Painting Area</name>\n"
    "    <description>Autonomous Drone Painting Target Wall</description>\n"
    "    <GroundOverlay>\n"
    "      <name>Target Wall</name>\n"
    "      <color>ddffffff</color>\n"
    "      <Icon>\n"
    "        <href>wall_overlay.png</href>\n"
    "      </Icon>\n"
    "      <LatLonBox>\n"
    "        <north>%.7f</north>\n"
    "        <south>%.7f</south>\n"
    "        <east>%.7f</east>\n"
    "        <west>%.7f</west>\n"
    "        <rotation>0</rotation>\n"
    "      </LatLonBox>\n"
    "    </GroundOverlay>\n"
    "    <Placemark>\n"
    "      <name>Drone Home</name>\n"
    "      <Style>\n"
    "        <IconStyle>\n"
    "          <color>ff0000ff</color>\n"
    "          <scale>1.2</scale>\n"
    '          <Icon><href>http://maps.google.com/mapfiles/kml/shapes/heliport.png</href></Icon>\n'
    "        </IconStyle>\n"
    "      </Style>\n"
    "      <Point>\n"
    "        <coordinates>%.7f,%.7f,0</coordinates>\n"
    "      </Point>\n"
    "    </Placemark>\n"
    "  </Document>\n"
    "</kml>\n"
) % (
    lat_center + half_h, lat_center - half_h,
    lon_center + half_w, lon_center - half_w,
    lon_center, lat_center,
)

with open("wall_overlay.kml", "w") as f:
    f.write(kml_text)
print("Created wall_overlay.kml")

# KMZ bundle
with zipfile.ZipFile("wall_overlay.kmz", "w", zipfile.ZIP_DEFLATED) as z:
    z.write("wall_overlay.kml", "doc.kml")
    z.write("wall_overlay.png", "wall_overlay.png")
print("Created wall_overlay.kmz (self-contained)")
