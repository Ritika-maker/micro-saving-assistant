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
app.secret_key = 'super_secret_key_for_dev'  
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  

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
            item_for_comp = {"name": matched['product_name'], "price": item['price']}
        else:
            item['normalized'] = item['name']
            item['category']   = ''
            item_for_comp = item
        
        alts = find_alternatives(item_for_comp, products_df)
        recs = recommend_alternatives(item, products, alts)
        recommendations[item['name']] = recs
        
        if recs:
            best_saving = recs[0].get('savings_pct', 0)
            total_savings += (item['price'] * best_saving / 100)
    
    dashboard_data = {
        "total_spent": round(total_spent, 2),
        "total_savings": round(total_savings, 2),
        "savings_pct": round((total_savings / total_spent * 100) if total_spent > 0 else 0, 1),
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

if __name__ == '__main__':
    app.run(debug=True, port=5000)