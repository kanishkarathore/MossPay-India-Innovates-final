from flask import Flask, request, jsonify, render_template, redirect, url_for, session
import database
from core_logic.nlp_standardizer import NLPStandardizer
from core_logic.carbon_engine import CarbonEngine
import sqlite3
from geopy.geocoders import Nominatim 
from geopy.distance import geodesic
import uuid
from datetime import datetime

app = Flask(__name__)
app.secret_key = "mosspay_hackathon_super_secret" 

print("[SYSTEM] Booting up MossPay AI & Carbon Engine...")
nlp = NLPStandardizer()
engine = CarbonEngine()
geolocator = Nominatim(user_agent="mosspay_locator")

# ==========================================
# UI ROUTES - GENERAL & VENDOR
# ==========================================
@app.route('/')
def landing_page(): return render_template('index.html')

@app.route('/vendor/login')
def vendor_login(): return render_template('vendor_login.html')

@app.route('/vendor/dashboard')
def vendor_dashboard():
    if 'vendor_id' not in session: return redirect(url_for('vendor_login'))
    with sqlite3.connect(database.DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT lifetime_co2e FROM users WHERE vendor_id = ?", (session['vendor_id'],))
        lifetime_co2 = cursor.fetchone()[0] or 0.0
        cursor.execute("SELECT SUM(quantity) FROM inventory WHERE vendor_id = ? AND packaging_type != 'plastic_single_use'", (session['vendor_id'],))
        green_qty = cursor.fetchone()[0] or 0.0
        cursor.execute("SELECT DISTINCT product_name FROM inventory WHERE vendor_id = ? AND quantity < 20 AND quantity > 0", (session['vendor_id'],))
        low_stock_rows = cursor.fetchall()
        
        restock_msg = "All stock levels healthy"
        if lifetime_co2 == 0.0: restock_msg = "Inventory is completely empty"
        elif len(low_stock_rows) > 0: restock_msg = f"{', '.join([r[0].title() for r in low_stock_rows])} running low"

    return render_template('dashboard.html', business_name=session.get('business_name'),
                           total_co2=round(lifetime_co2, 2), total_saved=round(green_qty * 0.1, 2),
                           restock_count=len(low_stock_rows), restock_msg=restock_msg)

@app.route('/vendor/profile')
def vendor_profile():
    if 'vendor_id' not in session: return redirect(url_for('vendor_login'))
    return render_template('vendor_profile.html', business_name=session.get('business_name'), 
                           profile=database.get_vendor_profile(session['vendor_id']))

@app.route('/vendor/inventory')
def vendor_inventory():
    if 'vendor_id' not in session: return redirect(url_for('vendor_login'))
    with sqlite3.connect(database.DB_NAME) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM inventory WHERE vendor_id = ? AND quantity > 0 ORDER BY id DESC", (session['vendor_id'],))
        return render_template('inventory.html', items=cursor.fetchall())

@app.route('/vendor/generate_ebill')
def generate_ebill():
    if 'vendor_id' not in session: return redirect(url_for('vendor_login'))
    with sqlite3.connect(database.DB_NAME) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM inventory WHERE vendor_id = ? AND quantity > 0", (session['vendor_id'],))
        return render_template('generate_ebill.html', inventory=[dict(row) for row in cursor.fetchall()])
    
@app.route('/vendor/customer_insights')
def vendor_customer_insights():
    if 'vendor_id' not in session: return redirect(url_for('vendor_login'))
    with sqlite3.connect(database.DB_NAME) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
       
        # aggregate by customer email/phone for vendor
        top_customers = cursor.execute('''
            SELECT t.buyer_phone, c.full_name, COUNT(*) AS visits,
                   SUM(t.price_per_unit * t.quantity) AS revenue,
                   SUM(t.inherited_co2e) AS co2
            FROM transactions t
            LEFT JOIN customers c ON c.phone_number = t.buyer_phone
            WHERE t.seller_id = ? AND t.status = 'Completed'
            GROUP BY t.buyer_phone
            ORDER BY revenue DESC
            LIMIT 10
        ''', (session['vendor_id'],)).fetchall()

        segments = cursor.execute('''
            SELECT
                SUM(CASE WHEN revenue >= 2000 THEN 1 ELSE 0 END) AS high_value,
                SUM(CASE WHEN revenue >= 500 AND revenue < 2000 THEN 1 ELSE 0 END) AS mid_value,
                SUM(CASE WHEN revenue < 500 THEN 1 ELSE 0 END) AS low_value
            FROM (
                SELECT t.buyer_phone, SUM(t.price_per_unit * t.quantity) AS revenue
                FROM transactions t
                WHERE t.seller_id = ? AND t.status = 'Completed'
                GROUP BY t.buyer_phone
            )
        ''', (session['vendor_id'],)).fetchone()

        total_customers = cursor.execute('SELECT COUNT(DISTINCT buyer_phone) FROM transactions WHERE seller_id = ? AND status = "Completed"', (session['vendor_id'],)).fetchone()[0]
        total_transactions = cursor.execute('SELECT COUNT(*) FROM transactions WHERE seller_id = ? AND status = "Completed"', (session['vendor_id'],)).fetchone()[0]
        total_revenue = cursor.execute('SELECT SUM(price_per_unit * quantity) FROM transactions WHERE seller_id = ? AND status = "Completed"', (session['vendor_id'],)).fetchone()[0] or 0

    return render_template('vendor_insights.html', top_customers=top_customers, segments=segments,
                           total_customers=total_customers, total_transactions=total_transactions,
                           total_revenue=round(total_revenue,2))


@app.route('/vendor/offers', methods=['GET', 'POST'])
def vendor_offers():
    if 'vendor_id' not in session:
        return redirect(url_for('vendor_login'))

    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        description = request.form.get('description', '').strip()
        discount = float(request.form.get('discount', 0) or 0)
        total_quantity = int(request.form.get('total_quantity', 0) or 0)
        expires_at = request.form.get('expires_at', None)

        if title and total_quantity > 0 and discount >= 0:
            database.create_offer(session['vendor_id'], title, description, discount, total_quantity, expires_at)
            return redirect(url_for('vendor_offers'))

    offers = database.get_offers_by_vendor(session['vendor_id'])
    return render_template('vendor_offers.html', offers=offers)


@app.route('/vendor/offers/<offer_id>/toggle', methods=['POST'])
def vendor_offer_toggle(offer_id):
    if 'vendor_id' not in session:
        return jsonify({'status': 'error', 'message': 'Login required'}), 401

    current = request.form.get('active', '0')
    database.set_offer_active(offer_id, current == '1')
    return redirect(url_for('vendor_offers'))


@app.route('/vendor/your_bills')
def your_bills():
    if 'vendor_id' not in session: return redirect(url_for('vendor_login'))
    with sqlite3.connect(database.DB_NAME) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute('''
            SELECT t.*, u.business_name as seller_name 
            FROM transactions t 
            JOIN users u ON t.seller_id = u.vendor_id 
            WHERE t.buyer_phone = ? 
            ORDER BY t.timestamp DESC
        ''', (session['phone_number'],))
        return render_template('your_bills.html', bills=cursor.fetchall())


@app.route('/vendor/discover')
def vendor_discover():
    if 'vendor_id' not in session: return redirect(url_for('vendor_login'))

    search_query = request.args.get('search', '').strip().lower()
    with sqlite3.connect(database.DB_NAME) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        if search_query:
            cursor.execute('''
                SELECT DISTINCT u.vendor_id, u.business_name, p.logo_url, p.shop_category, p.description, p.detailed_address
                FROM users u
                LEFT JOIN vendor_profiles p ON u.vendor_id = p.vendor_id
                LEFT JOIN inventory i ON u.vendor_id = i.vendor_id
                WHERE u.vendor_id != ? AND ((LOWER(i.product_name) LIKE ? AND i.quantity > 0) OR LOWER(u.business_name) LIKE ?)
            ''', (session['vendor_id'], f'%{search_query}%', f'%{search_query}%'))
        else:
            cursor.execute('''
                SELECT u.vendor_id, u.business_name, p.logo_url, p.shop_category, p.description, p.detailed_address
                FROM users u
                LEFT JOIN vendor_profiles p ON u.vendor_id = p.vendor_id
                WHERE u.vendor_id != ?
            ''', (session['vendor_id'],))

        vendors = [dict(row) for row in cursor.fetchall()]
        for vendor in vendors:
            cursor.execute('SELECT product_name, price, unit, quantity FROM inventory WHERE vendor_id = ? AND quantity > 0', (vendor['vendor_id'],))
            vendor['inventory'] = [dict(row) for row in cursor.fetchall()]

    return render_template('vendor_discover.html', vendors=vendors, search_query=search_query)


@app.route('/vendor/b2b')
def vendor_b2b():
    if 'vendor_id' not in session: return redirect(url_for('vendor_login'))
    return render_template('b2b_redirect.html')


@app.route('/vendor/transactions')
def vendor_transactions():
    if 'vendor_id' not in session: return redirect(url_for('vendor_login'))
    with sqlite3.connect(database.DB_NAME) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute('''SELECT * FROM transactions WHERE seller_id = ? ORDER BY timestamp DESC''', (session['vendor_id'],))
        return render_template('vendor_transactions.html', transactions=cursor.fetchall())

# ==========================================
# UI ROUTES - CUSTOMER
# ==========================================
@app.route('/customer')
def customer_index(): return redirect(url_for('customer_login'))

@app.route('/customer/login')
def customer_login(): return render_template('customer_login.html')

@app.route('/customer/dashboard')
def customer_dashboard():
    if 'customer_id' not in session: return redirect(url_for('customer_login'))
    with sqlite3.connect(database.DB_NAME) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        user = cursor.execute("SELECT * FROM customers WHERE customer_id = ?", (session['customer_id'],)).fetchone()
        higher_users = cursor.execute('SELECT COUNT(id) FROM customers WHERE location_name = ? AND total_co2_saved > ?', (user['location_name'], user['total_co2_saved'])).fetchone()[0]
        actual_rank = higher_users + 1
        co2 = user['total_co2_saved']
        
        if co2 < 10: sprout_emoji, sprout_title, sprout_target = "🌱", "Planted Seed", 10
        elif co2 < 50: sprout_emoji, sprout_title, sprout_target = "🌿", "Growing Sapling", 50
        else: sprout_emoji, sprout_title, sprout_target = "🌳", "Mighty Oak", co2 
        
        progress_pct = min(100, (co2 / sprout_target) * 100) if sprout_target > 0 else 0
        sprout_remaining = round(max(0, sprout_target - co2), 2)
        
    return render_template('customer_dashboard.html', full_name=user['full_name'], location_name=user['location_name'],
                           mosscoins=user['mosscoins'], co2_saved=round(co2, 2), eco_streak=user['eco_streak'],
                           city_rank=actual_rank, sprout_emoji=sprout_emoji, sprout_title=sprout_title,
                           sprout_remaining=sprout_remaining, progress_pct=progress_pct)

@app.route('/customer/discover')
def customer_discover():
    if 'customer_id' not in session: return redirect(url_for('customer_login'))
    search_query = request.args.get('search', '').strip().lower()
    with sqlite3.connect(database.DB_NAME) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        if search_query:
            cursor.execute('''SELECT DISTINCT u.vendor_id, u.business_name, p.logo_url, p.shop_category, p.description, p.detailed_address
                FROM users u LEFT JOIN vendor_profiles p ON u.vendor_id = p.vendor_id LEFT JOIN inventory i ON u.vendor_id = i.vendor_id
                WHERE (LOWER(i.product_name) LIKE ? AND i.quantity > 0) OR LOWER(u.business_name) LIKE ?''', (f'%{search_query}%', f'%{search_query}%'))
        else:
            cursor.execute('''SELECT u.vendor_id, u.business_name, p.logo_url, p.shop_category, p.description, p.detailed_address
                FROM users u LEFT JOIN vendor_profiles p ON u.vendor_id = p.vendor_id''')
        vendors = [dict(row) for row in cursor.fetchall()]
        for vendor in vendors:
            cursor.execute("SELECT product_name, price, unit, quantity FROM inventory WHERE vendor_id = ? AND quantity > 0", (vendor['vendor_id'],))
            vendor['inventory'] = [dict(row) for row in cursor.fetchall()]
    return render_template('customer_discover.html', vendors=vendors, search_query=search_query)

@app.route('/customer/bills')
def customer_bills():
    if 'customer_id' not in session: 
        return redirect(url_for('customer_login'))
    
    print(f"Customer phone: {session['phone_number']}")
    
    with sqlite3.connect(database.DB_NAME) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT t.id, t.txn_id, t.seller_id, t.buyer_customer_id, t.buyer_phone, t.product_name, t.quantity, t.parent_batch_id, t.inherited_co2e, t.price_per_unit, t.status, t.claimed, t.timestamp, u.business_name 
            FROM transactions t 
            JOIN users u ON t.seller_id = u.vendor_id 
            WHERE t.buyer_customer_id = ? AND t.status = 'Completed' 
            ORDER BY t.timestamp DESC
        ''', (session['customer_id'],))
        
        rows = cursor.fetchall()
        print(f"Fetched {len(rows)} transactions for phone {session['phone_number']}")
        receipts_dict = {}

        for r in rows:
            # CHANGE: Group by txn_id instead of just shop+date
            # This ensures every distinct 'Send' action is its own bill
            key = r['txn_id'] 
            
            if key not in receipts_dict:
                receipts_dict[key] = {
                    'seller_name': r['business_name'],
                    'date': r['timestamp'], # Keep full timestamp for uniqueness
                    'product_list': [],
                    'total_price': 0.0,
                    'total_co2_incurred': 0.0,
                    'claimed': r['claimed'],
                    'potential_coins': int(float(r['inherited_co2e']) * 0.15 * 10),
                    'txn_id': r['txn_id']
                }
            
            price = float(r['price_per_unit']) * float(r['quantity'])
            receipts_dict[key]['product_list'].append({
                'name': str(r['product_name']),
                'qty': float(r['quantity']),
                'price': price
            })
            receipts_dict[key]['total_price'] += price
            receipts_dict[key]['total_co2_incurred'] += float(r['inherited_co2e'])

        return render_template('customer_bills.html', bills=list(receipts_dict.values()))

@app.route('/customer/transactions')
def customer_transactions():
    if 'customer_id' not in session: return redirect(url_for('customer_login'))
    with sqlite3.connect(database.DB_NAME) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # We use SUM(...) as 'amount' so the HTML can find it
        cursor.execute('''
            SELECT t.timestamp, u.business_name as seller_name, t.txn_id,
            SUM(t.price_per_unit * t.quantity) as amount
            FROM transactions t 
            JOIN users u ON t.seller_id = u.vendor_id 
            WHERE t.buyer_customer_id = ? AND t.status = 'Completed' 
            GROUP BY t.txn_id
            ORDER BY t.timestamp DESC
        ''', (session['customer_id'],))
        transactions = cursor.fetchall()

    return render_template('customer_transactions.html', transactions=transactions)

@app.route('/customer/leaderboard')
def customer_leaderboard():
    if 'customer_id' not in session: return redirect(url_for('customer_login'))
    with sqlite3.connect(database.DB_NAME) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        user = cursor.execute("SELECT location_name FROM customers WHERE customer_id = ?", (session['customer_id'],)).fetchone()
        leaders = cursor.execute('''SELECT full_name, total_co2_saved, customer_id FROM customers WHERE location_name = ? AND total_co2_saved > 0
            ORDER BY total_co2_saved DESC LIMIT 50''', (user['location_name'],)).fetchall()
    return render_template('customer_leaderboard.html', city=user['location_name'], leaders=leaders, current_user_id=session['customer_id'])

@app.route('/customer/journey')
def customer_journey():
    if 'customer_id' not in session: return redirect(url_for('customer_login'))

    with sqlite3.connect(database.DB_NAME) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        purchases = cursor.execute('''
            SELECT t.*, u.business_name, u.location_name
            FROM transactions t
            JOIN users u ON t.seller_id = u.vendor_id
            WHERE (t.buyer_phone = ? OR t.buyer_customer_id = ?) AND t.status = 'Completed'
            ORDER BY t.timestamp DESC
        ''', (session['phone_number'], session['customer_id'])).fetchall()

        enriched = []
        for p in purchases:
            journey_steps = []

            # final stage: customer purchase from this vendor
            journey_steps.append({
                'stage': 'Customer Purchase',
                'vendor': p['business_name'],
                'location': p['location_name'],
                'product': p['product_name'],
                'quantity': p['quantity'],
                'co2': p['inherited_co2e'],
                'timestamp': p['timestamp'],
                'role': 'Retailer'
            })

            # trace upstream B2B chain by looking at vendor-seller transaction history
            previous_vendor_id = p['seller_id']
            current_product = p['product_name']
            max_hops = 6
            while max_hops > 0:
                max_hops -= 1

                vendor_info = cursor.execute('SELECT phone_number, business_name, location_name FROM users WHERE vendor_id = ?', (previous_vendor_id,)).fetchone()
                if not vendor_info:
                    break

                prior_txn = cursor.execute('''
                    SELECT t.*, u.business_name AS prior_seller_name, u.location_name AS prior_seller_location
                    FROM transactions t
                    JOIN users u ON t.seller_id = u.vendor_id
                    WHERE t.buyer_phone = ? AND t.product_name = ? AND t.status = 'Completed'
                    ORDER BY t.timestamp DESC
                    LIMIT 1
                ''', (vendor_info['phone_number'], current_product)).fetchone()

                if not prior_txn:
                    break

                # insert at beginning for upstream chain ordering
                journey_steps.insert(0, {
                    'stage': 'Supplier',
                    'vendor': prior_txn['prior_seller_name'],
                    'location': prior_txn['prior_seller_location'],
                    'product': prior_txn['product_name'],
                    'quantity': prior_txn['quantity'],
                    'co2': prior_txn['inherited_co2e'],
                    'timestamp': prior_txn['timestamp'],
                    'role': 'Supplier'
                })

                previous_vendor_id = prior_txn['seller_id']

            enriched.append({'txn': dict(p), 'journey': journey_steps})

    return render_template('customer_journey.html', purchases=enriched)

@app.route('/customer/redeem')
def customer_redeem():
    if 'customer_id' not in session: return redirect(url_for('customer_login'))
    with sqlite3.connect(database.DB_NAME) as conn:
        conn.row_factory = sqlite3.Row
        user = conn.cursor().execute("SELECT mosscoins FROM customers WHERE customer_id = ?", (session['customer_id'],)).fetchone()
        vendors = conn.cursor().execute("SELECT business_name FROM users LIMIT 4").fetchall()
    return render_template('customer_redeem.html', mosscoins=user['mosscoins'], vendors=vendors)

@app.route('/customer/referral')
def customer_referral():
    if 'customer_id' not in session: return redirect(url_for('customer_login'))
    return render_template('customer_referral.html', invite_code=session['customer_id'].upper())

@app.route('/customer/scan')
def customer_scan():
    if 'customer_id' not in session: return redirect(url_for('customer_login'))
    with sqlite3.connect(database.DB_NAME) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute('SELECT vendor_id, business_name FROM users')
        vendors = [dict(row) for row in cursor.fetchall()]
    return render_template('customer_scan.html', vendors=vendors)

@app.route('/vendor/scan')
def vendor_scan():
    if 'vendor_id' not in session: return redirect(url_for('vendor_login'))
    with sqlite3.connect(database.DB_NAME) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute('SELECT vendor_id, business_name FROM users')
        vendors = [dict(row) for row in cursor.fetchall()]
    return render_template('customer_scan.html', vendors=vendors)

@app.route('/api/get_vendor_items/<vendor_id>')
def get_vendor_items(vendor_id):
    with sqlite3.connect(database.DB_NAME) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        items = cursor.execute('SELECT batch_id, product_name, quantity, price, unit FROM inventory WHERE vendor_id = ? AND quantity > 0', (vendor_id,)).fetchall()
        return jsonify([dict(item) for item in items])

@app.route('/api/send_money_by_phone', methods=['POST'])
def send_money_by_phone():
    if 'customer_id' not in session and 'vendor_id' not in session: return jsonify({"status": "error", "message": "Login required"}), 401
    data = request.json
    to_phone = str(data.get('phone', '')).strip()
    amount = float(data.get('amount', 0) or 0)
    if not to_phone or amount <= 0:
        return jsonify({"status": "error", "message": "Phone and amount required"}), 400

    with sqlite3.connect(database.DB_NAME) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        target_vendor = cursor.execute('SELECT vendor_id FROM users WHERE phone_number = ?', (to_phone,)).fetchone()
        if not target_vendor:
            return jsonify({"status": "error", "message": "Recipient not found"}), 404

        sender_phone = session.get('phone_number')
        sender_customer = None
        if 'customer_id' in session:
            sender_customer = session['customer_id']

        txn_id = "PAY-" + uuid.uuid4().hex[:6].upper()
        cursor.execute('''INSERT INTO transactions (txn_id, seller_id, buyer_customer_id, buyer_phone, product_name, quantity, parent_batch_id, inherited_co2e, price_per_unit, status, claimed)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            (txn_id, target_vendor['vendor_id'], sender_customer, sender_phone, 'Phone Payment', 1, 'PHONEPAY', 0.0, amount, 'Completed', 1))
        conn.commit()

    return jsonify({"status": "success", "amount_paid": amount, "message": "Payment completed"})

# ==========================================
# API ROUTES
# ==========================================
@app.route('/api/add_inventory_item', methods=['POST'])
def add_inventory_item():
    if 'vendor_id' not in session: return jsonify({"status": "error"}), 401
    data = request.json
    
    qty = float(data['quantity'])
    qty_kg = qty if data['unit'] in ['kg', 'l'] else qty * 0.2
    
    # Calculation logic fix
    mfg_emission = round(qty_kg * 1.5, 2)
    pkg_type = data.get('packaging', 'jute')
    pkg_factor = 0.5 if pkg_type == 'plastic' else 0.1
    pkg_emission = round(qty_kg * pkg_factor, 2)
    shelf_emission = round(qty_kg * 0.05, 2)
    
    total_co2 = mfg_emission + pkg_emission + shelf_emission
    batch_id = f"BATCH-{uuid.uuid4().hex[:6].upper()}"

    with sqlite3.connect(database.DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute('''INSERT INTO inventory 
            (vendor_id, product_name, batch_id, quantity, unit, price, total_co2e, packaging_type)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)''', 
            (session['vendor_id'], data['name'].lower(), batch_id, qty, data['unit'], float(data['price']), total_co2, pkg_type))
        cursor.execute("UPDATE users SET lifetime_co2e = lifetime_co2e + ? WHERE vendor_id = ?", (total_co2, session['vendor_id']))
        conn.commit()

    return jsonify({
        "status": "success",
        "mfg": mfg_emission,
        "transport": 0,
        "packaging": pkg_emission,
        "shelf": shelf_emission,
        "total": total_co2
    })

@app.route('/api/send_ebill', methods=['POST'])
def send_ebill():
    if 'vendor_id' not in session: return jsonify({"status": "error"}), 401
    data = request.json
    buyer_phone = str(data.get('buyer_phone', '')).strip()
    print(f"Sending bill to phone: {buyer_phone}")
    
    cart = data.get('cart', [])

    with sqlite3.connect(database.DB_NAME) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # We check if the buyer is another Vendor
        is_vendor = cursor.execute("SELECT vendor_id FROM users WHERE phone_number = ?", (buyer_phone,)).fetchone()
        
        # If it's a Vendor, status is 'Pending' (needs acceptance)
        # If it's a Customer, status is 'Completed' (automatic)
        final_status = 'Pending' if is_vendor else 'Completed'

        buyer_customer_row = cursor.execute("SELECT customer_id FROM customers WHERE phone_number = ?", (buyer_phone,)).fetchone()
        buyer_customer_id = buyer_customer_row['customer_id'] if buyer_customer_row else None

        for item_data in cart:
            qty = float(item_data['quantity'])
            item = cursor.execute("SELECT * FROM inventory WHERE batch_id = ?", (item_data['batch_id'],)).fetchone()
            if not item: continue
            
            proportion = qty / float(item['quantity'])
            co2_inc = round(float(item['total_co2e']) * proportion, 2)
            
            cursor.execute('''INSERT INTO transactions 
                (txn_id, seller_id, buyer_customer_id, buyer_phone, product_name, quantity, parent_batch_id, inherited_co2e, price_per_unit, status, claimed)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''', 
                ("TXN-"+uuid.uuid4().hex[:6].upper(), session['vendor_id'], buyer_customer_id, buyer_phone, item['product_name'], 
                 qty, item_data['batch_id'], co2_inc, item['price'], final_status, False))
            
            cursor.execute("UPDATE inventory SET quantity = quantity - ?, total_co2e = total_co2e - ? WHERE batch_id = ?", 
                           (qty, co2_inc, item_data['batch_id']))

        conn.commit()
    return jsonify({"status": "success"})

@app.route('/api/accept_ebill', methods=['POST'])
def accept_ebill():
    if 'vendor_id' not in session: return jsonify({"status": "error"}), 401
    data = request.json
    
    try:
        txn_id = str(data.get('txn_id'))
        new_price = float(data.get('new_price'))
        pkg_type = str(data.get('packaging', 'jute'))

        with sqlite3.connect(database.DB_NAME) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            # 1. Fetch original transaction
            txn = cursor.execute("SELECT * FROM transactions WHERE txn_id = ?", (txn_id,)).fetchone()
            if not txn: 
                return jsonify({"status": "error", "message": "Transaction record not found"}), 404
            
            # 2. Safety Math (Ensuring no None values)
            qty = float(txn['quantity'] or 0)
            inherited_co2 = float(txn['inherited_co2e'] or 0)
            cost_price = float(txn['price_per_unit'] or 0)

            # Price Validation
            if new_price < cost_price:
                return jsonify({"status": "error", "message": f"Price cannot be lower than cost (₹{cost_price})"}), 400

            # 3. Leg-2 Carbon Logic
            # Adding distance and packaging factors
            transport_co2 = round(10.0 * 0.05 * qty, 2) # Default 10km for demo
            new_pkg_co2 = round(qty * (0.5 if pkg_type == 'plastic' else 0.1), 2)
            total_co2 = round(inherited_co2 + transport_co2 + new_pkg_co2, 2)

            # 4. Update Inventory
            child_batch = f"RE-{uuid.uuid4().hex[:6].upper()}"
            cursor.execute('''INSERT INTO inventory 
                (vendor_id, product_name, batch_id, quantity, unit, price, total_co2e, packaging_type)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)''', 
                (session['vendor_id'], str(txn['product_name']), child_batch, qty, 'kg', new_price, total_co2, pkg_type))
            
            # 5. Finalize status and Merchant total
            cursor.execute("UPDATE transactions SET status = 'Completed' WHERE txn_id = ?", (txn_id,))
            cursor.execute("UPDATE users SET lifetime_co2e = lifetime_co2e + ? WHERE vendor_id = ?", (total_co2, session['vendor_id']))
            
            conn.commit()

        return jsonify({"status": "success", "total_co2": total_co2})

    except Exception as e:
        print(f"[CRITICAL ERROR] Accept Ebill Failed: {str(e)}")
        return jsonify({"status": "error", "message": "Server internal math error"}), 500

@app.route('/api/process_payment', methods=['POST'])
def process_payment():
    if 'customer_id' not in session: return jsonify({"status": "error"}), 401
    data = request.json
    qty = float(data['quantity'])
    with sqlite3.connect(database.DB_NAME) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        item = cursor.execute("SELECT * FROM inventory WHERE batch_id = ?", (data['batch_id'],)).fetchone()
        if not item or float(item['quantity']) < qty: return jsonify({"status": "error", "message": "No stock"})
        co2_inc = round(float(item['total_co2e']) * (qty / float(item['quantity'])), 2)
        co2_sav = round(co2_inc * 0.15, 2)
        cursor.execute('''INSERT INTO transactions (txn_id, seller_id, buyer_phone, product_name, quantity, parent_batch_id, inherited_co2e, price_per_unit, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'Completed')''', ("PAY-"+uuid.uuid4().hex[:6].upper(), data['vendor_id'], session['phone_number'], item['product_name'], qty, data['batch_id'], co2_inc, item['price']))
        cursor.execute("UPDATE inventory SET quantity = quantity - ?, total_co2e = total_co2e - ? WHERE batch_id = ?", (qty, co2_inc, data['batch_id']))
        cursor.execute("UPDATE customers SET total_co2_saved = total_co2_saved + ?, mosscoins = mosscoins + ? WHERE customer_id = ?", (co2_sav, int(co2_sav*10), session['customer_id']))
        conn.commit()
    return jsonify({"status": "success", "amount_paid": item['price']*qty, "co2_saved": co2_sav, "coins_earned": int(co2_sav*10)})

@app.route('/api/claim_mosscoins', methods=['POST'])
def claim_mosscoins():
    if 'customer_id' not in session: return jsonify({"status": "error"}), 401
    data = request.json
    txn_id = data.get('txn_id')
    with sqlite3.connect(database.DB_NAME) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        txn = cursor.execute("SELECT * FROM transactions WHERE txn_id = ? AND buyer_customer_id = ?", (txn_id, session['customer_id'])).fetchone()
        if not txn or txn['claimed']:
            return jsonify({"status": "error", "message": "Already claimed or invalid"}), 400
        co2_inc = float(txn['inherited_co2e'])
        co2_sav = round(co2_inc * 0.15, 2)
        coins = int(co2_sav * 10)
        cursor.execute("UPDATE transactions SET claimed = TRUE WHERE txn_id = ?", (txn_id,))
        cursor.execute("UPDATE customers SET total_co2_saved = total_co2_saved + ?, mosscoins = mosscoins + ? WHERE customer_id = ?", (co2_sav, coins, session['customer_id']))
        conn.commit()
    return jsonify({"status": "success", "coins_earned": coins, "co2_saved": co2_sav})

@app.route('/api/pay_utility', methods=['POST'])
def pay_utility():
    if 'customer_id' not in session: return jsonify({"status": "error"}), 401
    data = request.json
    with sqlite3.connect(database.DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE customers SET mosscoins = mosscoins - ? WHERE customer_id = ?", (data['coins_used'], session['customer_id']))
        conn.commit()
    return jsonify({"status": "success", "message": "Utility bill paid!"})

@app.route('/api/register', methods=['POST'])
def register_vendor():
    data = request.json
    try:
        # Fallback coordinates for registration stability
        vid = database.register_user(data['business_name'], data['email'], data['phone_number'], data['password'], data['location_name'], 23.25, 77.41)
        return jsonify({"status": "success", "message": "User registered successfully!"})
    except Exception as e: return jsonify({"status": "error", "message": str(e)}), 400

@app.route('/api/login', methods=['POST'])
def login_vendor():
    data = request.json
    with sqlite3.connect(database.DB_NAME) as conn:
        conn.row_factory = sqlite3.Row
        user = conn.cursor().execute("SELECT * FROM users WHERE email = ? AND password = ?", (data['email'], data['password'])).fetchone()
        if user:
            session['vendor_id'] = user['vendor_id']; session['business_name'] = user['business_name']; session['phone_number'] = user['phone_number']
            return jsonify({"status": "success", "redirect_url": "/vendor/dashboard"})
    return jsonify({"status": "error", "message": "Invalid credentials."}), 401

@app.route('/api/customer_register', methods=['POST'])
def register_customer():
    data = request.json
    try:
        customer_id = database.register_customer(data['full_name'], data['email'], data['phone_number'], data['password'], data['location_name'])
        return jsonify({"status": "success", "message": "Account created successfully!"})
    except Exception as e: return jsonify({"status": "error", "message": str(e)}), 400

@app.route('/api/customer_login', methods=['POST'])
def login_customer():
    data = request.json
    with sqlite3.connect(database.DB_NAME) as conn:
        conn.row_factory = sqlite3.Row
        user = conn.cursor().execute("SELECT * FROM customers WHERE email = ? AND password = ?", (data['email'], data['password'])).fetchone()
        if user:
            session['customer_id'] = user['customer_id']; session['full_name'] = user['full_name']; session['phone_number'] = user['phone_number']
            return jsonify({"status": "success", "redirect_url": "/customer/dashboard"})
    return jsonify({"status": "error", "message": "Invalid credentials."}), 401

if __name__ == '__main__':
    app.run(port=5000, debug=True)