import sqlite3
import uuid
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_NAME = os.path.join(BASE_DIR, "mosspay.db")

def init_db():
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        
        # Vendor Users Table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                vendor_id TEXT UNIQUE NOT NULL,
                business_name TEXT NOT NULL,
                email TEXT UNIQUE NOT NULL,
                phone_number TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL,
                location_name TEXT NOT NULL,
                lat REAL NOT NULL,
                lng REAL NOT NULL,
                lifetime_co2e REAL DEFAULT 0.0
            )
        ''')

        # CUSTOMER TABLE: Now tracks location, real CO2 saved, and streak!
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS customers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                customer_id TEXT UNIQUE NOT NULL,
                full_name TEXT NOT NULL,
                email TEXT UNIQUE NOT NULL,
                phone_number TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL,
                location_name TEXT NOT NULL,
                mosscoins INTEGER DEFAULT 0,
                total_co2_saved REAL DEFAULT 0.0,
                eco_streak INTEGER DEFAULT 0,
                last_purchase_date DATE
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS vendor_profiles (
                vendor_id TEXT PRIMARY KEY,
                shop_category TEXT,
                description TEXT,
                logo_url TEXT,
                website TEXT,
                contact_person TEXT,
                contact_mobile TEXT,
                detailed_address TEXT
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS inventory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                vendor_id TEXT NOT NULL,
                product_name TEXT NOT NULL,
                batch_id TEXT NOT NULL,
                quantity REAL NOT NULL,
                unit TEXT NOT NULL,
                price REAL NOT NULL,
                total_co2e REAL NOT NULL,
                packaging_type TEXT NOT NULL,
                date_added TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                txn_id TEXT UNIQUE NOT NULL,
                seller_id TEXT NOT NULL,
                buyer_customer_id TEXT,
                buyer_phone TEXT NOT NULL,
                product_name TEXT NOT NULL,
                quantity REAL NOT NULL,
                parent_batch_id TEXT NOT NULL,
                inherited_co2e REAL NOT NULL,
                price_per_unit REAL NOT NULL,
                status TEXT DEFAULT 'Pending',
                claimed BOOLEAN DEFAULT FALSE,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS offers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                offer_id TEXT UNIQUE NOT NULL,
                vendor_id TEXT NOT NULL,
                title TEXT NOT NULL,
                description TEXT,
                discount_percentage REAL DEFAULT 0.0,
                total_quantity INTEGER DEFAULT 0,
                claimed_count INTEGER DEFAULT 0,
                active BOOLEAN DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expires_at TIMESTAMP
            )
        ''')
        conn.commit()

# Add new columns if not exist for compatibility
try:
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute('ALTER TABLE transactions ADD COLUMN claimed BOOLEAN DEFAULT FALSE')
        conn.commit()
except:
    pass

try:
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute('ALTER TABLE transactions ADD COLUMN buyer_customer_id TEXT')
        conn.commit()
except:
    pass

# --- VENDOR METHODS ---
def register_user(business_name, email, phone_number, password, location_name, lat, lng):
    vendor_id = "VND-" + str(uuid.uuid4())[:6].upper()
    phone_number = phone_number.strip()
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO users (vendor_id, business_name, email, phone_number, password, location_name, lat, lng)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (vendor_id, business_name, email, phone_number, password, location_name, lat, lng))
        conn.commit()
    return vendor_id

def upsert_vendor_profile(vendor_id, category, desc, logo, website, contact, mobile, address):
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO vendor_profiles 
            (vendor_id, shop_category, description, logo_url, website, contact_person, contact_mobile, detailed_address)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (vendor_id, category, desc, logo, website, contact, mobile, address))
        conn.commit()

def get_vendor_profile(vendor_id):
    with sqlite3.connect(DB_NAME) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM vendor_profiles WHERE vendor_id = ?", (vendor_id,))
        return cursor.fetchone()

# --- OFFERS METHODS ---
def create_offer(vendor_id, title, description, discount_percentage, total_quantity, expires_at=None):
    offer_id = "OFF-" + str(uuid.uuid4())[:8].upper()
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO offers (offer_id, vendor_id, title, description, discount_percentage, total_quantity, expires_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (offer_id, vendor_id, title, description, float(discount_percentage), int(total_quantity), expires_at))
        conn.commit()
    return offer_id


def get_offers_by_vendor(vendor_id):
    with sqlite3.connect(DB_NAME) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        return cursor.execute('SELECT * FROM offers WHERE vendor_id = ? ORDER BY created_at DESC', (vendor_id,)).fetchall()


def set_offer_active(offer_id, active):
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute('UPDATE offers SET active = ? WHERE offer_id = ?', (1 if active else 0, offer_id))
        conn.commit()


def increment_offer_claim(offer_id):
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute('UPDATE offers SET claimed_count = claimed_count + 1 WHERE offer_id = ?', (offer_id,))
        conn.commit()

# --- CUSTOMER METHODS ---
def register_customer(full_name, email, phone_number, password, location_name):
    customer_id = "CUS-" + str(uuid.uuid4())[:6].upper()
    phone_number = phone_number.strip()
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO customers (customer_id, full_name, email, phone_number, password, location_name)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (customer_id, full_name, email, phone_number, password, location_name))
        conn.commit()
    return customer_id

init_db()