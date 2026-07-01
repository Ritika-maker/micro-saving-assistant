from flask import Flask, render_template, request, jsonify, redirect, url_for, flash, Response
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
import os, sqlite3, json, csv
from io import StringIO
from datetime import datetime
from werkzeug.security import generate_password_hash
import pandas as pd

try:
    import pytesseract
    from PIL import Image
    OCR_AVAILABLE = True
except ImportError:
    OCR_AVAILABLE = False

from receipt_processor import parse_receipt_text, fuzzy_match
from product_db import load_products
from price_comparison import find_alternatives
from recommendation_engine import recommend_alternatives
from models import (init_db, register_user, get_user, save_analysis,
                    get_user_history, get_or_create_store, get_all_stores,
                    upsert_product_price, search_products)

app = Flask(__name__)
app.secret_key = 'super_secret_key_for_dev'
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
init_db()

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

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
    return User(user[0], user[1]) if user else None

@app.route('/')
def index():
    stores = get_all_stores()
    return render_template('index.html', stores=stores)

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
            login_user(User(user_data[0], user_data[1]))
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

@app.route('/search')
@login_required
def product_search():
    q = request.args.get('q', '').strip()
    if len(q) < 2:
        return jsonify([])
    return jsonify(search_products(q, limit=15))

@app.route('/stores')
@login_required
def stores_list():
    return jsonify(get_all_stores())

@app.route('/upload', methods=['POST'])
@login_required
def upload_receipt():
    raw_text = None
    store_name = request.form.get('store_name', '').strip() or 'General Market'

    if 'receipt_text' in request.form and request.form['receipt_text'].strip():
        raw_text = request.form['receipt_text']
    elif 'file' in request.files:
        file = request.files['file']
        if file.filename == '':
            return jsonify({"error": "No file selected"}), 400
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], file.filename)
        file.save(file_path)
        if file.filename.lower().endswith(('.png', '.jpg', '.jpeg')):
            if OCR_AVAILABLE:
                try:
                    raw_text = pytesseract.image_to_string(Image.open(file_path))
                except Exception as e:
                    raw_text = f"OCR Error: {str(e)}"
            else:
                return jsonify({"error": "OCR not available"}), 400
        elif file.filename.endswith('.txt'):
            with open(file_path, 'r', encoding='utf-8') as f:
                raw_text = f.read()
        else:
            return jsonify({"error": "Unsupported file type"}), 400

    if not raw_text:
        return jsonify({"error": "No input provided"}), 400

    store_id = get_or_create_store(store_name)
    products = load_products()
    products_df = pd.DataFrame(products)

    receipt_data = parse_receipt_text(raw_text, store_name=store_name)

    total_spent = 0
    total_savings = 0
    recommendations = {}

    for item in receipt_data['items']:
        total_spent += item['price']
        matched, confidence = fuzzy_match(item['name'], products)

        if matched:
            item['normalized'] = matched['product_name']
            item['category']   = matched.get('category', '')
            item['brand']      = matched.get('brand', '')
            item['confidence'] = round(confidence * 100)

            db_price   = float(matched.get('price') or 0)
            user_price = float(item['price'])
            if abs(user_price - db_price) > 1:
                upsert_product_price(
                    product_name = matched['product_name'],
                    category     = matched.get('category', ''),
                    brand        = matched.get('brand', ''),
                    unit         = matched.get('unit', ''),
                    health_score = matched.get('health_score', 5),
                    price        = user_price,
                    unit_price   = user_price,
                    store_id     = store_id
                )
            item_for_comp = {"name": matched['product_name'], "price": item['price']}
        else:
            item['normalized'] = item['name']
            item['category']   = ''
            item['brand']      = ''
            item['confidence'] = 0
            upsert_product_price(
                product_name = item['name'],
                category='', brand='', unit='', health_score=5,
                price=float(item['price']), unit_price=float(item['price']),
                store_id=store_id
            )
            item_for_comp = item

        item_brand = item.get('brand', '')
        alts = find_alternatives(item_for_comp, products_df,
                                  item_brand=item_brand, current_store=store_name)
        recs = recommend_alternatives(item, products, alts,
                                       item_brand=item_brand,
                                       match_confidence=confidence if matched else None)
        recommendations[item['name']] = recs

        if recs:
            best_alt_price = recs[0].get('alt_price', item['price'])
            total_savings += max(0, item['price'] - best_alt_price)

    dashboard_data = {
        "total_spent":   int(round(total_spent)),
        "total_savings": int(round(total_savings)),
        "savings_pct":   round((total_savings / total_spent * 100) if total_spent > 0 else 0, 1),
        "store_name":    store_name,
        "items":         receipt_data['items'],
        "recommendations": recommendations,
        "raw_text":      raw_text[:500]
    }

    save_analysis(current_user.id, raw_text[:1000],
                  dashboard_data["total_spent"], dashboard_data["total_savings"],
                  dashboard_data["savings_pct"],
                  items_count=len(receipt_data['items']),
                  store_name=store_name,
                  raw_data=json.dumps(dashboard_data))

    return jsonify(dashboard_data)

@app.route('/export/<int:analysis_id>')
@login_required
def export_report(analysis_id):
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    c.execute("SELECT raw_data FROM analyses WHERE id=? AND user_id=?",
              (analysis_id, current_user.id))
    result = c.fetchone()
    conn.close()
    if not result:
        return "Analysis not found", 404
    try:
        data = json.loads(result[0])
        output = StringIO()
        writer = csv.writer(output)
        writer.writerow(['Item','Price (NPR)','Store','Confidence%',
                         'Best Alternative','Alt Price (NPR)','Best Store','Savings%'])
        for item in data.get('items', []):
            recs = data.get('recommendations', {}).get(item['name'], [])
            if recs:
                best = recs[0]
                writer.writerow([item['name'], item['price'],
                                  data.get('store_name',''), item.get('confidence',''),
                                  best.get('alternative',''), best.get('alt_price',''),
                                  best.get('best_store',''), f"{best.get('savings_pct','')}%"])
            else:
                writer.writerow([item['name'], item['price'],
                                  data.get('store_name',''), item.get('confidence',''),
                                  '—','—','—','—'])
        writer.writerow([])
        writer.writerow(['Total Spent', data['total_spent'],'','','','','',''])
        writer.writerow(['Potential Savings', data['total_savings'],
                         f"({data['savings_pct']}%)",'','','','',''])
        return Response(output.getvalue(), mimetype='text/csv',
                        headers={"Content-Disposition":
                                 f"attachment;filename=savings_report_{analysis_id}.csv"})
    except Exception as e:
        return f"Error: {str(e)}", 500

# ── Compare page ──────────────────────────────────────────────────────────────

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
    q        = request.args.get('q', '').strip().lower()
    category = request.args.get('category', '').strip()

    conn = sqlite3.connect('users.db')
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    c.execute("SELECT id, store_name FROM stores ORDER BY store_name")
    all_stores = [{"id": r["id"], "store_name": r["store_name"]} for r in c.fetchall()]

    where_clauses, params = [], []
    if q:
        where_clauses.append("(LOWER(p.product_name) LIKE ? OR LOWER(p.brand) LIKE ?)")
        params += [f'%{q}%', f'%{q}%']
    if category:
        where_clauses.append("p.category = ?")
        params.append(category)
    where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

    c.execute(f'''
        SELECT p.product_name, p.category, p.brand, p.unit, p.health_score,
               sp.price, sp.unit_price, sp.updated_at,
               s.id AS store_id, s.store_name
        FROM products p
        JOIN store_prices sp ON sp.product_id = p.id
        JOIN stores s ON s.id = sp.store_id
        {where_sql}
        ORDER BY p.category, p.product_name, sp.unit_price ASC
    ''', params)
    rows = c.fetchall()

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

    return jsonify({"stores": all_stores, "products": list(products_map.values())})


if __name__ == '__main__':
    app.run(debug=True, port=5000)