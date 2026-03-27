import sqlite3
from database import DB_NAME

with sqlite3.connect(DB_NAME) as conn:
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    print('=== customers ===')
    for r in c.execute('SELECT customer_id, full_name, phone_number, mosscoins FROM customers'):
        print(dict(r))
    print('=== transactions ===')
    for r in c.execute('SELECT txn_id, seller_id, buyer_phone, product_name, quantity, status, claimed FROM transactions'):
        print(dict(r))
