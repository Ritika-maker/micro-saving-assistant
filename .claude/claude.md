Project Context
This is my BCA college final-year project at Tribhuvan University (2026).

Project Name: Micro-Savings Assistant

Purpose: Help grocery shoppers in Nepal find cheaper alternatives by analyzing receipts. Users can enter items manually, paste text, or upload images (with OCR). The system matches products using fuzzy algorithms, compares prices across stores, and recommends savings opportunities while tracking user history.

This is an academic college project, so prioritize:

Correctness

Simplicity

Explainability

Maintainable code

Features I can confidently explain during viva

Do not unnecessarily over-engineer the project.

Core Technology Stack
Layer	Technology
Backend	Flask, Flask-Login, Werkzeug
Database	SQLite
OCR	Tesseract, pytesseract, Pillow
Data Processing	pandas, difflib
Frontend	HTML, Tailwind CSS, Jinja2
Auth	bcrypt password hashing
Project Structure
text
micro_savings_assistant/
├── app.py                    # Main Flask application (all routes)
├── models.py                 # Database operations (users, products, stores, analyses)
├── product_db.py             # Product catalogue with store prices
├── receipt_processor.py      # Text parsing + fuzzy matching
├── price_comparison.py       # Finds cheaper alternatives
├── recommendation_engine.py  # Formats recommendations
├── main.py                   # CLI test runner
├── products.csv              # Initial product data (NPR prices)
├── products2.csv             # Alternative product data
├── receipt_example.txt       # Sample receipt
├── users.db                  # SQLite database (auto-created)
├── uploads/                  # Temporary file storage
└── templates/
    ├── _nav.html             # Navigation bar (shared)
    ├── home.html             # Landing page
    ├── index.html            # Receipt analyzer (main tool)
    ├── dashboard.html        # History & savings tracking
    ├── compare.html          # Store price comparison
    ├── login.html            # Login page
    └── register.html         # Registration page
Database Schema
Core Tables
users: id, username, password (hashed), created_at

analyses: id, user_id, receipt_text, total_spent, total_savings, savings_pct, analysis_date, items_count, store_name, raw_data (JSON)

products: id, product_name (UNIQUE), category, brand, unit, health_score (1-10), created_at

stores: id, store_name (UNIQUE), location, created_at

store_prices: id, product_id, store_id, price, unit_price, updated_at (UNIQUE: product_id, store_id)

Key Relationships
User → analyses (one-to-many)

Product → store_prices (one-to-many)

Store → store_prices (one-to-many)

Product ↔ Store (many-to-many via store_prices)

Four Core Algorithms
1. Receipt Parsing & Normalization
File: receipt_processor.py → parse_receipt_text()

Process:

Split text into lines

Remove OCR artifacts: re.sub(r'[^\w\s\.\-\,]', ' ', line)

Extract price pattern: (\d+\.?\d*)\s*$

Extract quantity pattern: (\d+)([a-zA-Z]*)

Return: {"name": str, "quantity": int, "price": float}

2. Fuzzy Matching Algorithm
File: receipt_processor.py → fuzzy_match()

Formula:

Keyword Score = overlapping_words / max(len(item_words), len(product_words))

Composite Score = (keyword_score × 0.7) + (sequence_ratio × 0.3)

Threshold: 0.35 (accept matches above this)

3. Price Comparison Engine
File: price_comparison.py → find_alternatives()

Process:

Load products into pandas DataFrame

Filter by same category

Skip same brand (if brand specified)

Calculate savings: (user_price - alt_price) / user_price × 100

Filter alternatives with ≥5% savings

Return top 3 alternatives with store-level prices

4. Recommendation Engine
File: recommendation_engine.py → recommend_alternatives()

Logic:

Calculate savings amount and percentage

Mark healthier alternatives (health_score ≥ 8 for food categories)

Generate human-readable explanations

Include best store and price range information

Food Categories: {'Dairy', 'Bakery', 'Grains', 'Protein', 'Meat', 'Fruits', 'Beverages', 'Vegetables', 'Oils'}

Key Routes
Route	Method	Auth	Description
/	GET	No	Landing page
/app	GET	Yes	Analyzer tool
/register	GET/POST	No	User registration
/login	GET/POST	No	User login
/logout	GET	Yes	Logout
/dashboard	GET	Yes	Savings history
/upload	POST	Yes	Receipt analysis
/compare	GET	Yes	Store comparison page
/api/compare	GET	Yes	API for comparison data
/export/<analysis_id>	GET	Yes	CSV export
/search	GET	Yes	Product search API
/stores	GET	Yes	Store list API
Important Functions
User Management (models.py)
python
register_user(username, password)          # Returns bool
get_user(username, password)               # Returns (id, username) or None
get_or_create_store(store_name)            # Returns store_id
get_all_stores()                           # Returns list of stores
Product Operations (models.py)
python
upsert_product_price(product_name, category, brand, unit, health_score, price, unit_price, store_id)
search_products(query, limit=15)           # Returns matching products
get_store_price_comparison(product_name)   # Returns all store prices
Product Loading (product_db.py)
python
load_products(store_id=None)               # Returns products with prices
load_products_with_store_prices()          # Returns products with per-store prices
Analysis History (models.py)
python
save_analysis(user_id, receipt_text, total_spent, total_savings, savings_pct, items_count, store_name, raw_data)
get_user_history(user_id)                  # Returns last 20 analyses
Common Implementation Patterns
Database Connection Pattern
python
conn = sqlite3.connect(DB_PATH)
c = conn.cursor()
# Execute queries
conn.commit()
conn.close()
Product Price Upsert Pattern
python
# Insert or ignore product
c.execute("INSERT OR IGNORE INTO products (product_name, category, brand, unit, health_score, created_at) VALUES (?, ?, ?, ?, ?, ?)", ...)
# Get product_id
c.execute("SELECT id FROM products WHERE product_name = ?", (name,))
# Upsert price with ON CONFLICT
c.execute("INSERT INTO store_prices (product_id, store_id, price, unit_price, updated_at) VALUES (?, ?, ?, ?, ?) ON CONFLICT(product_id, store_id) DO UPDATE SET price = excluded.price, unit_price = excluded.unit_price, updated_at = excluded.updated_at", ...)
Flask Route with Authentication
python
@app.route('/protected')
@login_required
def protected():
    return render_template('page.html')
Initial Setup
bash
# Install dependencies
pip install flask flask-login pandas pillow pytesseract

# Tesseract installation (Windows)
# Download from: https://github.com/UB-Mannheim/tesseract/wiki
# Or: winget install tesseract

# Run development server
python app.py  # Opens on http://127.0.0.1:5000
First Run: Database auto-creates and imports products from CSV if empty.

Data Flow (Full Pipeline)
text
User Input (text/image/file)
    ↓
OCR Processing (if image) → Tesseract OCR
    ↓
Receipt Parsing → parse_receipt_text()
    ↓
For each item:
    ├── Fuzzy Matching → fuzzy_match() 
    ├── Product Normalization
    ├── Price Comparison → find_alternatives()
    ├── Recommendation Generation → recommend_alternatives()
    └── Product Price Upsert → upsert_product_price()
    ↓
Aggregate totals (total_spent, total_savings, savings_pct)
    ↓
Save Analysis → save_analysis()
    ↓
Return JSON to client
    ↓
Dashboard displays results
File Format Requirements
CSV Import (products.csv, products2.csv):

text
product_name,category,brand,price,unit,unit_price,health_score
Amul Milk 1L,Dairy,Amul,90,liter,90,8
Receipt Text Format (one item per line):

text
Amul Milk 1L    90
Whole Wheat Bread 400g    120
Image Formats: JPG, PNG (max 16MB)

Academic References (Report Chapter 2)
Pande, K. et al. - "Exploring Two Decades of Personal Financial Planning" - Importance of item-level expense tracking

Ashfauk Ahamed & Shahif - "AI-Powered Personal Finance Assistant" - OCR + NLP for expense tracking

Kebede, M. et al. - "Financial Literacy and Management of Personal Finance" - Consumer knowledge gap

Singh & Kaur - "Consumer Behavior and Price Sensitivity" - Brand loyalty despite cheaper alternatives

Chen & Li - "Smart Shopping Systems" - Micro-savings accumulation validation

Performance Benchmarks (From Report Section 4.3)
Algorithm Performance:

Receipt Parsing: ~185ms (5 items), ~342ms (10 items)

Fuzzy Matching: ~45ms per item

Price Comparison: ~30ms per item

Recommendation Generation: ~25ms per item

OCR Accuracy:

Character Accuracy: 94.3%

Word Accuracy: 89.7%

Price Extraction: 92%

Database Operations:

Save Analysis: ~78ms

Retrieve History: ~92ms

Export CSV: ~134ms

Viva/Defense Assistance
When I ask questions related to my college defense/viva:

Answer based primarily on the actual project implementation.

Use simple English.

Give answers that sound natural when spoken.

For technical questions, structure answers as:

Definition
→ How it works
→ How it is used in my project
→ Simple example if useful

Example:

Question: "Why did you use fuzzy matching?"

Answer: "I used fuzzy matching because receipt item names often don't exactly match database product names. For example, a user might type 'Amul Milk' while the database has 'Amul Milk 1L'. Fuzzy matching compares the similarity between strings and finds the closest match, ensuring the system can still recommend alternatives even when the user doesn't type the exact product name."

Important Safety Rules
Before Modifying Code
Inspect the relevant files first

Understand existing architecture

Reuse existing functions where possible

Make the smallest necessary change

Do not rewrite unrelated files

Do not change working functionality unnecessarily

Do not add dependencies unless required

Preserve existing naming conventions

When a Bug Occurs
Read the error

Identify the affected file/function

Fix the direct cause

Test that specific feature again

Do not test the entire project

Git Rules
Do not automatically create commits

Do not automatically push to GitHub

Only make Git commits/pushes when I explicitly ask

Never run destructive commands: git reset --hard, git clean -fd, git push --force unless I explicitly request them

Common Errors & Solutions
Error	Solution
ImportError: No module named pytesseract	Install: pip install pytesseract
Tesseract not found	Install Tesseract or set path
Database locked	Close all database connections or use timeout parameter
Form data missing	Check enctype: multipart/form-data for file uploads
404 on static files	Flask serves static from /static/ folder
Quick Reference
When user asks about:

Matching products: Use fuzzy_match() in receipt_processor.py - composite score with 0.35 threshold

Price comparison: Use find_alternatives() in price_comparison.py - pandas-based filtering, 5% savings threshold

Recommendations: Use recommend_alternatives() in recommendation_engine.py - adds explanations and health flags

Adding products: Use upsert_product_price() in models.py - handles insert/update automatically

User history: Use get_user_history() in models.py - returns last 20 analyses

OCR issues: Check Tesseract installation and image quality in app.py /upload route

Database schema: See init_db() in models.py - creates all tables automatically

Project Keywords
#MicroSavings #PersonalFinance #ReceiptOCR #PriceComparison #Flask #SQLite #Tesseract #FuzzyMatching #TailwindCSS #BCA #TribhuvanUniversity