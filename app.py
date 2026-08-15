from flask import Flask, render_template, request, jsonify, redirect, url_for, flash, Response
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
import os, sqlite3, json, csv, uuid
from io import StringIO
from datetime import datetime
from werkzeug.security import generate_password_hash
from werkzeug.utils import secure_filename
import pandas as pd

from ocr_processor import (OCR_AVAILABLE, OCRError, is_image_file,
                           image_to_receipt_text, ALLOWED_IMAGE_EXTENSIONS)

from receipt_processor import (parse_receipt_text, fuzzy_match, match_item,
                               build_item, classify_confidence)
from product_db import load_products
from price_comparison import find_alternatives
from recommendation_engine import recommend_alternatives
from performance import Timings
from models import (init_db, register_user, get_user, save_analysis,
                    get_user_history, get_or_create_store, get_all_stores,
                    upsert_product_price, search_products, get_analysis,
                    save_analysis_items, get_analysis_items,
                    price_freshness, get_price_history, compare_basket_across_stores,
                    get_spending_summary, get_monthly_summary, get_spending_by_store,
                    get_savings_trend, get_top_savings_opportunities,
                    get_savings_goal, set_savings_goal, record_actual_savings)

app = Flask(__name__)
# Secret key comes from the environment; the development fallback is random,
# so a forgotten configuration can never ship a known key.
app.secret_key = os.environ.get('SECRET_KEY') or os.urandom(32).hex()
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024      # 16 MB hard limit
# Receipt images are only needed during OCR; keeping them is off by default.
app.config['KEEP_UPLOADS'] = os.environ.get('KEEP_UPLOADS', '0') == '1'

ALLOWED_TEXT_EXTENSIONS = ('.txt',)

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
init_db()

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Please log in to access this page.'

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
def landing():
    # Always show home page regardless of login state
    return render_template('home.html')

@app.route('/app')
@login_required
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
    return render_template(
        'dashboard.html',
        history       = get_user_history(current_user.id),
        summary       = get_spending_summary(current_user.id),
        month         = get_monthly_summary(current_user.id),
        by_store      = get_spending_by_store(current_user.id),
        trend         = get_savings_trend(current_user.id),
        opportunities = get_top_savings_opportunities(current_user.id),
        goal          = get_savings_goal(current_user.id),
    )

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

# ── Upload / OCR helpers ─────────────────────────────────────────────────────

def _store_uploaded_file(file):
    """
    Validate an uploaded file and save it under a random name.

    Returns (path, error_message). The original filename is never used on
    disk - it only decides the extension - which rules out path traversal and
    name collisions between users.
    """
    original = secure_filename(file.filename or '')
    extension = os.path.splitext(original)[1].lower()

    if extension not in ALLOWED_IMAGE_EXTENSIONS + ALLOWED_TEXT_EXTENSIONS:
        return None, ("Unsupported file type. Please upload a JPG, PNG or TXT file.")

    # Second check: the browser-declared content type must agree with the
    # extension (a .png that announces itself as a PDF is rejected).
    mimetype = (file.mimetype or '').lower()
    if extension in ALLOWED_IMAGE_EXTENSIONS and not mimetype.startswith('image/'):
        return None, "That file does not look like an image."
    if extension in ALLOWED_TEXT_EXTENSIONS and mimetype and \
            not mimetype.startswith('text/'):
        return None, "That file does not look like a text file."

    path = os.path.join(app.config['UPLOAD_FOLDER'], f"{uuid.uuid4().hex}{extension}")
    file.save(path)
    return path, None


def _read_receipt_input(timings):
    """
    Get receipt text from the request: pasted text, a .txt file, or OCR on an
    image. Returns (raw_text, source, error_message).
    """
    pasted = request.form.get('receipt_text', '')
    if pasted.strip():
        return pasted, 'text', None

    if 'file' not in request.files:
        return None, None, "No input provided."

    file = request.files['file']
    if not file or file.filename == '':
        return None, None, "No file selected"

    path, error = _store_uploaded_file(file)
    if error:
        return None, None, error

    try:
        if is_image_file(path):
            if not OCR_AVAILABLE:
                return None, None, ("OCR is not available on this server. "
                                    "Please paste the receipt text instead.")
            try:
                with timings.measure('ocr'):
                    return image_to_receipt_text(path), 'image', None
            except OCRError as e:
                return None, None, str(e)
        with open(path, 'r', encoding='utf-8', errors='ignore') as f:
            return f.read(), 'file', None
    finally:
        # The image was only needed for OCR - don't keep user receipts around
        if not app.config['KEEP_UPLOADS']:
            try:
                os.remove(path)
            except OSError:
                pass


def _preview_items(items, products):
    """Attach a provisional match + confidence so the review screen can show it."""
    for item in items:
        matched, score, level, label = match_item(item, products)
        item['suggested_match'] = matched['product_name'] if matched else ''
        item['confidence']       = round(score * 100)
        item['confidence_level'] = level
        item['confidence_label'] = label
    return items


@app.route('/upload', methods=['POST'])
@login_required
def upload_receipt():
    """
    Step 1 of the analysis: read the receipt and return the extracted items
    for the user to review and correct. No analysis is saved yet.
    """
    timings = Timings()
    store_name = request.form.get('store_name', '').strip() or 'General Market'

    raw_text, source, error = _read_receipt_input(timings)
    if error:
        return jsonify({"error": error}), 400
    if not raw_text or not raw_text.strip():
        return jsonify({"error": "No readable receipt content was found."}), 400

    with timings.measure('parsing'):
        receipt_data = parse_receipt_text(raw_text, store_name=store_name)

    if not receipt_data['items']:
        return jsonify({"error": "No receipt items could be read. "
                                 "Check the image quality or enter the items manually."}), 400

    with timings.measure('matching'):
        items = _preview_items(receipt_data['items'], load_products())

    if app.debug:
        timings.log('extract')

    return jsonify({
        "items":          items,
        "store_name":     store_name,
        "source":         source,
        "detected_total": receipt_data.get('total'),
        "raw_text":       raw_text[:2000],
        "timings":        timings.as_dict(),
    })


@app.route('/analyze', methods=['POST'])
@login_required
def analyze_receipt():
    """
    Step 2: analyse the items the user confirmed on the review screen.
    Accepts JSON: {store_name, raw_text, items: [{product_name, quantity, unit, price}]}
    """
    timings = Timings()
    payload = request.get_json(silent=True) or {}
    store_name = (payload.get('store_name') or '').strip() or 'General Market'
    raw_text = payload.get('raw_text') or ''

    with timings.measure('parsing'):
        items = []
        for entry in payload.get('items', []):
            name = (entry.get('product_name') or entry.get('name') or '').strip()
            if not name:
                continue
            try:
                price = float(entry.get('price'))
            except (TypeError, ValueError):
                continue
            if price <= 0:
                continue
            unit = (entry.get('unit') or '').strip()
            quantity = entry.get('quantity')
            # Rebuild the description from the corrected fields so quantity,
            # unit and unit price stay consistent. A countable unit needs the
            # number with it ('Eggs 12 pcs'); a pack size already carries its
            # own number ('Amul Milk 1L').
            if unit and not any(ch.isdigit() for ch in unit) and str(quantity).isdigit():
                description = f"{name} {quantity} {unit}"
            else:
                description = f"{name} {unit}".strip()
            item = build_item(description, price, quantity=quantity, unit=unit)
            item['product_name'] = name
            items.append(item)

    if not items:
        return jsonify({"error": "No valid items to analyse."}), 400

    return jsonify(_run_analysis(items, store_name, raw_text, timings))


def _run_analysis(items, store_name, raw_text, timings):
    """
    Shared analysis pipeline: match -> compare -> recommend -> save.
    Returns the dashboard payload.
    """
    store_id = get_or_create_store(store_name)
    products = load_products()
    products_df = pd.DataFrame(products)

    total_spent = 0.0
    total_savings = 0.0
    recommendations = {}

    for item in items:
        total_spent += item['price']

        with timings.measure('matching'):
            matched, confidence, level, label = match_item(item, products)

        item['confidence']       = round(confidence * 100)
        item['confidence_level'] = level
        item['confidence_label'] = label

        if matched:
            item['normalized'] = matched['product_name']
            item['category']   = matched.get('category', '')
            item['brand']      = matched.get('brand', '')

            # Learn the price the user actually paid (per unit, not the line total)
            db_price = float(matched.get('unit_price') or matched.get('price') or 0)
            if abs(item['unit_price'] - db_price) > 1:
                upsert_product_price(
                    product_name = matched['product_name'],
                    category     = matched.get('category', ''),
                    brand        = matched.get('brand', ''),
                    unit         = matched.get('unit', ''),
                    health_score = matched.get('health_score', 5),
                    price        = item['unit_price'],
                    unit_price   = item['unit_price'],
                    store_id     = store_id
                )
            item_for_comp = dict(item, name=matched['product_name'])
        else:
            item['normalized'] = item.get('product_name') or item['name']
            item['category']   = ''
            item['brand']      = ''
            upsert_product_price(
                product_name = item['normalized'],
                category='', brand='', unit=item.get('unit', ''), health_score=5,
                price=item['unit_price'], unit_price=item['unit_price'],
                store_id=store_id
            )
            item_for_comp = item

        item_brand = item.get('brand', '')
        with timings.measure('comparison'):
            alts = find_alternatives(item_for_comp, products_df,
                                     item_brand=item_brand, current_store=store_name)
        with timings.measure('recommendation'):
            recs = recommend_alternatives(item, products, alts,
                                          item_brand=item_brand,
                                          match_confidence=confidence if matched else None)
        recommendations[item['name']] = recs

        if recs:
            total_savings += recs[0].get('savings_amount', 0)

    # Which store would this basket be cheapest at?
    basket_names = [i.get('normalized') or i['name'] for i in items]
    basket = compare_basket_across_stores(basket_names)

    dashboard_data = {
        "total_spent":     int(round(total_spent)),
        "total_savings":   int(round(total_savings)),
        "savings_pct":     round((total_savings / total_spent * 100) if total_spent > 0 else 0, 1),
        "store_name":      store_name,
        "items":           items,
        "recommendations": recommendations,
        "basket":          basket,
        "raw_text":        raw_text[:500],
        "timings":         timings.as_dict(),
    }

    analysis_id = save_analysis(current_user.id, raw_text[:1000],
                                dashboard_data["total_spent"], dashboard_data["total_savings"],
                                dashboard_data["savings_pct"],
                                items_count=len(items),
                                store_name=store_name,
                                raw_data=json.dumps(dashboard_data))

    # Same results in queryable form (used by the dashboard statistics)
    save_analysis_items(analysis_id, items, recommendations)

    dashboard_data["analysis_id"] = analysis_id
    if app.debug:
        timings.log('analysis')
    return dashboard_data

@app.route('/analysis/<int:analysis_id>')
@login_required
def analysis_detail(analysis_id):
    """Full breakdown of one saved analysis."""
    analysis = get_analysis(analysis_id, current_user.id)
    if not analysis:
        return "Analysis not found", 404
    return render_template('analysis.html', analysis=analysis,
                           data=analysis['data'],
                           # structured rows; empty for analyses saved before
                           # the analysis_items table existed
                           stored_items=get_analysis_items(analysis_id))


@app.route('/analysis/<int:analysis_id>/used', methods=['POST'])
@login_required
def mark_recommendation_used(analysis_id):
    """
    User confirms they actually bought a recommended alternative.
    Only this action turns potential savings into actual savings.
    """
    payload = request.get_json(silent=True) or {}
    try:
        amount = float(payload.get('amount', 0))
    except (TypeError, ValueError):
        return jsonify({"error": "Invalid amount"}), 400
    if amount <= 0:
        return jsonify({"error": "Invalid amount"}), 400
    if not record_actual_savings(analysis_id, current_user.id, amount):
        return jsonify({"error": "Analysis not found"}), 404
    return jsonify({"ok": True, "goal": get_savings_goal(current_user.id)})


@app.route('/api/price-history')
@login_required
def api_price_history():
    product = request.args.get('product', '').strip()
    if not product:
        return jsonify({"product": "", "history": []})
    return jsonify({"product": product,
                    "history": get_price_history(product)})


@app.route('/api/basket', methods=['POST'])
@login_required
def api_basket():
    """Estimate the cost of a list of products at every store."""
    payload = request.get_json(silent=True) or {}
    names = [str(n) for n in payload.get('products', []) if str(n).strip()]
    return jsonify({"stores": compare_basket_across_stores(names)})


@app.route('/goal', methods=['POST'])
@login_required
def save_goal():
    """Set (or update) this month's savings goal."""
    raw = (request.form.get('target_amount') or
           (request.get_json(silent=True) or {}).get('target_amount'))
    try:
        target = float(raw)
    except (TypeError, ValueError):
        flash('Enter a valid goal amount.', 'error')
        return redirect(url_for('dashboard'))
    if target <= 0:
        flash('Goal must be greater than zero.', 'error')
        return redirect(url_for('dashboard'))
    set_savings_goal(current_user.id, target)
    flash('Monthly savings goal updated.', 'success')
    return redirect(url_for('dashboard'))


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
        writer.writerow(['Item','Qty','Unit','Total Price (NPR)','Unit Price (NPR)',
                         'Store','Confidence%','Confidence',
                         'Best Alternative','Alt Unit Price (NPR)','Best Store',
                         'Savings%','Savings (NPR)'])
        for item in data.get('items', []):
            recs = data.get('recommendations', {}).get(item['name'], [])
            base = [item.get('product_name') or item['name'],
                    item.get('quantity', 1), item.get('unit', ''),
                    item['price'], item.get('unit_price', item['price']),
                    data.get('store_name',''), item.get('confidence',''),
                    item.get('confidence_label', '')]
            if recs:
                best = recs[0]
                writer.writerow(base + [best.get('alternative',''), best.get('alt_price',''),
                                        best.get('best_store',''),
                                        f"{best.get('savings_pct','')}%",
                                        best.get('savings_amount','')])
            else:
                writer.writerow(base + ['—','—','—','—','—'])
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
        level, label = price_freshness(r["updated_at"])
        products_map[key]["store_prices"][r["store_id"]] = {
            "price":           int(round(r["price"])),
            "unit_price":      int(round(r["unit_price"])),
            "updated_at":      r["updated_at"],
            "store_name":      r["store_name"],
            "freshness_level": level,      # fresh / recent / older / unknown
            "freshness_label": label,
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


# ── Error handlers (never leak internal details to the user) ─────────────────

@app.errorhandler(413)
def file_too_large(error):
    return jsonify({"error": "That file is too large. The limit is 16 MB."}), 413


@app.errorhandler(500)
def internal_error(error):
    app.logger.exception('Unhandled server error')
    if request.path.startswith('/api/') or request.accept_mimetypes.best == 'application/json':
        return jsonify({"error": "Something went wrong while processing your "
                                 "request. Please try again."}), 500
    return "Something went wrong while processing your request.", 500


if __name__ == '__main__':
    # Set SECRET_KEY in the environment before running in production.
    app.run(debug=True, port=5000)