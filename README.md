# Micro-Savings Assistant

**Full-featured Flask web app** with user authentication, image OCR, and history.

## Features
- ✅ User Registration & Login (Flask-Login + SQLite)
- ✅ Receipt text paste
- ✅ **Image upload + Tesseract OCR** (JPG/PNG)
- ✅ .txt file upload
- ✅ Fuzzy matching & smart recommendations
- ✅ Savings calculations
- ✅ Per-user analysis history
- ✅ Responsive Tailwind UI

## Setup (Windows / Any OS)

```bash
cd micro_savings_assistant

# Install dependencies
pip install flask flask-login pandas pillow pytesseract

# Install Tesseract OCR (Windows):
# Download from: https://github.com/UB-Mannheim/tesseract/wiki
# Add to PATH or install via winget: winget install tesseract

# Run the app
python app.py
```

Open **http://127.0.0.1:5000**

**Test Credentials**:
- Register a new account or use demo.

## Project Structure
- `app.py` - Main Flask app with auth + OCR
- `models.py` - SQLite DB for users & history
- `templates/` - HTML pages
- `products.csv` - Expand with Kaggle data
- Other modules remain as before

**Note**: For production, use proper password hashing (already done), secure secret_key, and environment variables.

All requirements implemented! Expand products.csv with real Kaggle datasets for better results. 

Happy saving! 