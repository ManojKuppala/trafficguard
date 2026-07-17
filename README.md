# TrafficGuard AI – Traffic Violation Detection System

TrafficGuard AI is an automated traffic enforcement system that uses computer vision (YOLOv8) and Optical Character Recognition (EasyOCR) to detect traffic violations from images or video feeds. It automatically generates digital E-Challans (fine tickets) for offending vehicles.

## 🚀 Key Features
- **Helmet Violation Detection**: Identifies riders without helmets.
- **Triple Riding Detection**: Detects if 3 or more people are riding a single motorcycle.
- **Mobile Usage Detection**: Spots riders using mobile phones while driving.
- **Automated License Plate Extraction**: Crops and reads the license plate of the violating motorcycle.
- **Automated E-Challan**: Generates and persists digital tickets with fine breakdowns into a relational database.

---

## 🛠️ Technology Stack
- **Backend Framework**: Python + Flask
- **Computer Vision**: OpenCV (`cv2`) for image/video frame processing.
- **Object Detection**: Ultralytics YOLO (`YOLOv8` architecture).
- **OCR Engine**: Falls back to **EasyOCR**.
- **Frontend**: HTML5, Vanilla CSS (Custom Design System with CSS Variables), and Vanilla JavaScript with **GSAP** (GreenSock) for high-performance animations and ScrollTrigger effects.

---

## 🧠 AI Models Used
The system utilizes 4 independently trained YOLO `.pt` models to break down the complex scene into manageable detections:

1. **`motorcycle.pt`**: Detects all motorcycles/bikes in the frame.
2. **`person_phone.pt`**: Detects persons and mobile phones.
3. **`helmet.pt`**: Detects helmets and explicit "no-helmet" instances.
4. **`license.pt`**: Detects vehicle license plates.

---

## ⚙️ How the Detection Logic Works (`detector.py`)

The system doesn't just blindly detect objects; it maps them together structurally. When a frame is processed:

### 1. Model Inference
All 4 YOLO models run simultaneously on the input frame. To ensure high recall, the base confidence thresholds are set intentionally low (`0.30` for motorcycles, `0.15` for others). The system relies on *spatial geometry* (overlap logic) to filter out false positives rather than strict AI confidence alone.

### 2. Entity Association (Rider Mapping)
- The system iterates through every detected **motorcycle**.
- It looks for **persons** whose bounding boxes significantly *overlap* with the motorcycle's bounding box. These persons are grouped as "riders" associated specifically with that motorcycle.
- *(Fallback)* If a motorcycle is found but no person is detected overlapping it, a "synthetic rider" bounding box is generated in the top half of the motorcycle to ensure violations aren't entirely missed.

### 3. Violation Checks (Per Motorcycle)
Once riders are grouped to a motorcycle, the system checks for violations:

- **Triple Riding**: If the count of real riders associated with the motorcycle is `3` or more.
- **Helmet Violation**: The system calculates a "head box" (top 45% of the rider's body). If this head box does *not* overlap with a detected `helmet`, or if it explicitly overlaps with a `no-helmet` detection, a violation is flagged.
- **Mobile Usage**: A phone violation is flagged if a detected phone:
  1. Overlaps any of the rider's bodies.
  2. Is within 300px of the motorcycle's center.
  3. Is inside an expanded "halo" region around the motorcycle.
  4. Has its exact center point inside that halo.
  *(Note: Phone detection requires a strict AI confidence of `>= 0.45` to prevent false positives).*

### 4. License Plate OCR & Cropping
- If any violations are found on a motorcycle, the system searches for a detected `license plate` that physically overlaps with the motorcycle's space.
- The plate is cropped and passed through a custom **5-variant image preprocessing pipeline** (including resizing, Otsu thresholding, CLAHE, and Bilateral filtering).
- The OCR engine runs on all 5 variants. The results are scored against a Regex pattern (`[A-Z]{2}[0-9]{1,2}[A-Z]{1,3}[0-9]{3,4}`) matching standard Indian license plates. The highest-scoring text is kept.
- Finally, the original image is cropped tightly around the violating motorcycle and its riders, bounding boxes are drawn, and the image is saved to `static/results`.

---

## 📄 E-Challan Generation (`challan.py`)

When violations are detected, the system generates an automated fine based on a fixed table:
- Helmet: ₹1000
- Triple Riding: ₹2000
- Mobile Usage: ₹1500

Records are stored in a local SQLite database (`trafficguard.db`) mapping challans to violations for relational integrity.

---

## 🏃 How to Run the Project (Local Development)

1. Activate your virtual environment:
   ```cmd
   d:\MiniProject\project\venv\Scripts\Activate.ps1
   ```
2. Start the Flask Backend:
   ```cmd
   cd d:\MiniProject\project\venv\backend
   python app.py
   ```
3. Open your browser and navigate to `http://127.0.0.1:5000`

---

## 💻 How to Install & Run on a New Laptop

If you are presenting this on another machine, follow these steps:

**1. Extract the Project**
- Unzip `traffic-guard-ai.zip` into a new folder.

**2. Install Python**
- Ensure Python (3.9 to 3.11 recommended) is installed on the new laptop.

**3. Create a Virtual Environment**
Open Command Prompt / PowerShell in the extracted folder and run:
```cmd
python -m venv venv
venv\Scripts\activate
```

**4. Install Dependencies**
```cmd
pip install -r requirements.txt
```

**5. Start the Application**
```cmd
cd venv/backend
python app.py
```
*(The very first time you run it, it may take 1-2 minutes to download EasyOCR English language packs. Ensure you have an internet connection during this first run).*

Then open `http://127.0.0.1:5000` in the browser!
