from flask import Flask, render_template, request, jsonify, redirect, url_for, flash, session, Response
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
import os
import sqlite3
import pandas as pd
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
import pytesseract
import json
from PIL import Image
import io

from receipt_processor import parse_receipt_text, fuzzy_match
from product_db import load_products
from price_comparison import find_alternatives
from recommendation_engine import recommend_alternatives
from models import init_db, register_user, get_user, save_analysis, get_user_history
import csv
from io import StringIO

app = Flask(__name__)
app.secret_key = 'super_secret_key_for_dev'  # Change in production
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max upload

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
init_db()

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

products = load_products()
products_df = pd.DataFrame(products)

class User(UserMixin):
    def __init__(self, id, username):
        self.id = id
        self.username = username

@login_manager.user_loader
def load_user(user_id):
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    c.execute("SELECT id, username FROM users WHERE id=?", (user_id,))
    user = c.fetchone()
    conn.close()
    if user:
        return User(user[0], user[1])
    return None

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        if register_user(username, generate_password_hash(password)):
            flash('Registration successful! Please login.', 'success')
            return redirect(url_for('login'))
        else:
            flash('Username already exists.', 'error')
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user_data = get_user(username, password)
        if user_data:
            user = User(user_data[0], user_data[1])
            login_user(user)
            return redirect(url_for('dashboard'))
        flash('Invalid credentials', 'error')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))

@app.route('/dashboard')
@login_required
def dashboard():
    history = get_user_history(current_user.id)
    return render_template('dashboard.html', history=history)

@app.route('/upload', methods=['POST'])
@login_required
def upload_receipt():
    raw_text = None
    
    if 'receipt_text' in request.form and request.form['receipt_text'].strip():
        raw_text = request.form['receipt_text']
    elif 'file' in request.files:
        file = request.files['file']
        if file.filename == '':
            return jsonify({"error": "No file selected"}), 400
        
        filename = file.filename
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(file_path)
        
        if filename.lower().endswith(('.png', '.jpg', '.jpeg')):
            try:
                img = Image.open(file_path)
                raw_text = pytesseract.image_to_string(img)
            except Exception as e:
                raw_text = f"OCR Error: {str(e)}"
        elif filename.endswith('.txt'):
            with open(file_path, 'r', encoding='utf-8') as f:
                raw_text = f.read()
        else:
            raw_text = "Unsupported file type. Please use .txt or image."
    
    if not raw_text:
        return jsonify({"error": "No input provided"}), 400

    receipt_data = parse_receipt_text(raw_text)
    
    total_spent = 0
    total_savings = 0
    recommendations = {}
    
    for item in receipt_data['items']:
        total_spent += item['price']
        matched = fuzzy_match(item['name'], products)
        if matched:
            item['normalized'] = matched['product_name']
            item['category']   = matched.get('category', '')
            item['brand']      = matched.get('brand', '')
            item_for_comp = {"name": matched['product_name'], "price": item['price']}
        else:
            item['normalized'] = item['name']
            item['category']   = ''
            item['brand']      = ''
            item_for_comp = item
        
        item_brand = item.get('brand', '')
        alts = find_alternatives(item_for_comp, products_df, item_brand=item_brand)
        recs = recommend_alternatives(item, products, alts, item_brand=item_brand)
        recommendations[item['name']] = recs
        
        # Per-item saving: difference between item price and best alternative price
        if recs:
            best_alt_price = recs[0].get('alt_price', item['price'])
            item_saving = max(0, item['price'] - best_alt_price)
            total_savings += item_saving
    
    total_spent_int  = int(round(total_spent))
    total_savings_int = int(round(total_savings))

    dashboard_data = {
        "total_spent":   total_spent_int,
        "total_savings": total_savings_int,
        "savings_pct":   round((total_savings / total_spent * 100) if total_spent > 0 else 0, 1),
        "items": receipt_data['items'],
        "recommendations": recommendations,
        "raw_text": raw_text[:500]
    }
    
    save_analysis(current_user.id, raw_text[:1000], dashboard_data["total_spent"], 
                  dashboard_data["total_savings"], dashboard_data["savings_pct"],
                  items_count=len(receipt_data['items']),
                  raw_data=json.dumps(dashboard_data))
    
    return jsonify(dashboard_data)

@app.route('/export/<int:analysis_id>')
@login_required
def export_report(analysis_id):
    """Export analysis as CSV"""
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    c.execute("SELECT raw_data FROM analyses WHERE id=? AND user_id=?", (analysis_id, current_user.id))
    result = c.fetchone()
    conn.close()
    
    if not result:
        return "Analysis not found", 404
    
    try:
        data = json.loads(result[0])
        output = StringIO()
        writer = csv.writer(output)
        
        writer.writerow(['Item', 'Price', 'Normalized Name', 'Best Alternative', 'Alt Price', 'Savings %'])
        for item in data.get('items', []):
            recs = data.get('recommendations', {}).get(item['name'], [])
            if recs:
                best = recs[0]
                writer.writerow([
                    item['name'],
                    item['price'],
                    item.get('normalized', ''),
                    best.get('alternative', ''),
                    best.get('alt_price', ''),
                    f"{best.get('savings_pct', '')}%"
                ])
            else:
                writer.writerow([item['name'], item['price'], item.get('normalized', ''), '—', '—', '—'])
        
        writer.writerow([])
        writer.writerow(['Total Spent', data['total_spent'], '', '', '', ''])
        writer.writerow(['Potential Savings', data['total_savings'], f"({data['savings_pct']}%)", '', '', ''])
        
        return Response(
            output.getvalue(),
            mimetype='text/csv',
            headers={"Content-Disposition": f"attachment;filename=savings_report_{analysis_id}.csv"}
        )
    except Exception as e:
        return f"Error generating report: {str(e)}", 500

# ── Store comparison routes ───────────────────────────────────────────────────

@app.route('/compare')
@login_required
def compare():
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    c.execute("SELECT DISTINCT category FROM products WHERE category != '' ORDER BY category")
    categories = [r[0] for r in c.fetchall()]
    conn.close()
    return render_template('compare.html', categories=categories)


@app.route('/api/compare')
@login_required
def api_compare():
    """
    Returns product × store price matrix.
    Joins: products → store_prices → stores (all in users.db).
    Also pulls confidence history from past analyses for the current user.
    """
    q        = request.args.get('q', '').strip().lower()
    category = request.args.get('category', '').strip()

    conn = sqlite3.connect('users.db')
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    # All stores
    c.execute("SELECT id, store_name FROM stores ORDER BY store_name")
    all_stores = [{"id": r["id"], "store_name": r["store_name"]} for r in c.fetchall()]

    # Build WHERE for product filters
    where_clauses, params = [], []
    if q:
        where_clauses.append("(LOWER(p.product_name) LIKE ? OR LOWER(p.brand) LIKE ?)")
        params += [f'%{q}%', f'%{q}%']
    if category:
        where_clauses.append("p.category = ?")
        params.append(category)
    where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

    # Fetch product + store price rows
    c.execute(f'''
        SELECT
            p.product_name,
            p.category,
            p.brand,
            p.unit,
            p.health_score,
            sp.price,
            sp.unit_price,
            sp.updated_at,
            s.id        AS store_id,
            s.store_name
        FROM products p
        JOIN store_prices sp ON sp.product_id = p.id
        JOIN stores       s  ON s.id          = sp.store_id
        {where_sql}
        ORDER BY p.category, p.product_name, sp.unit_price ASC
    ''', params)
    rows = c.fetchall()

    # Pull confidence history from past analyses
    c.execute('''
        SELECT raw_data FROM analyses
        WHERE user_id = ? AND raw_data IS NOT NULL AND raw_data != '{}'
        ORDER BY analysis_date DESC LIMIT 30
    ''', (current_user.id,))
    conf_history = {}
    for (raw,) in c.fetchall():
        try:
            data = json.loads(raw)
            for item in data.get('items', []):
                name = item.get('normalized') or item.get('name', '')
                conf = item.get('confidence')
                if name and conf is not None:
                    conf_history.setdefault(name, []).append(int(conf))
        except Exception:
            pass

    conn.close()

    # Group rows into product objects keyed by product_name
    from collections import OrderedDict
    products_map = OrderedDict()
    for r in rows:
        key = r["product_name"]
        if key not in products_map:
            confs    = conf_history.get(key, [])
            avg_conf = round(sum(confs) / len(confs)) if confs else None
            products_map[key] = {
                "product_name":       key,
                "category":           r["category"],
                "brand":              r["brand"],
                "unit":               r["unit"],
                "health_score":       r["health_score"],
                "avg_confidence":     avg_conf,
                "confidence_history": confs,
                "store_prices":       {},
                "best_store_id":      None,
                "worst_store_id":     None,
                "price_spread":       0,
            }
        products_map[key]["store_prices"][r["store_id"]] = {
            "price":      int(round(r["price"])),
            "unit_price": int(round(r["unit_price"])),
            "updated_at": r["updated_at"],
            "store_name": r["store_name"],
        }

    # Compute best / worst store and price spread per product
    for prod in products_map.values():
        prices = [(sid, sp["unit_price"]) for sid, sp in prod["store_prices"].items()]
        if len(prices) > 1:
            best  = min(prices, key=lambda x: x[1])
            worst = max(prices, key=lambda x: x[1])
            prod["best_store_id"]  = best[0]
            prod["worst_store_id"] = worst[0]
            prod["price_spread"]   = worst[1] - best[1]
        elif prices:
            prod["best_store_id"]  = prices[0][0]
            prod["worst_store_id"] = prices[0][0]
            prod["price_spread"]   = 0

    return jsonify({
        "stores":   all_stores,
        "products": list(products_map.values()),
    })


if __name__ == '__main__':
    app.run(debug=True, port=5000)