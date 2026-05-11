from flask import Flask, render_template, request, redirect, url_for, flash, abort
import sqlite3, os, urllib.parse

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'rawda-secret-2024')

ADMIN_TOKEN   = os.environ.get('ADMIN_TOKEN', '1912003')
# ✏️ غيّر الرقم ده لرقمك — بدون + وبدون مسافات
WHATSAPP_NUM  = os.environ.get('WHATSAPP_NUM', '201094918310')

DB_PATH = os.path.join(os.path.dirname(__file__), 'rawda.db')

# ─── DB ──────────────────────────────────────────────────────

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def check_token(token):
    if token != ADMIN_TOKEN:
        abort(404)

def init_db():
    conn = get_db()
    # جدول الموبايلات — مع youtube_url
    conn.execute('''
        CREATE TABLE IF NOT EXISTS mobiles (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT NOT NULL,
            brand       TEXT NOT NULL,
            condition   TEXT NOT NULL,
            price       REAL NOT NULL,
            storage     TEXT,
            ram         TEXT,
            color       TEXT,
            description TEXT,
            image_url   TEXT,
            youtube_url TEXT,
            created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    # أضف العمود لو الجدول موجود بدون youtube_url (migration بسيطة)
    try:
        conn.execute('ALTER TABLE mobiles ADD COLUMN youtube_url TEXT')
    except Exception:
        pass

    # جدول المبيعات (History)
    conn.execute('''
        CREATE TABLE IF NOT EXISTS sales (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            mobile_id  INTEGER,
            name       TEXT NOT NULL,
            brand      TEXT NOT NULL,
            condition  TEXT NOT NULL,
            price      REAL NOT NULL,
            sold_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            notes      TEXT
        )
    ''')

    count = conn.execute('SELECT COUNT(*) FROM mobiles').fetchone()[0]
    if count == 0:
        samples = [
            ('Samsung Galaxy S24 Ultra','Samsung','new',4999,'256GB','12GB','أسود','هاتف رائد بكاميرا 200 ميجابكسل وقلم S Pen','https://via.placeholder.com/300x400/1a1a2e/ffffff?text=S24+Ultra',''),
            ('Samsung Galaxy A55','Samsung','new',1899,'128GB','8GB','أزرق','هاتف متوسط الفئة بتصميم أنيق','https://via.placeholder.com/300x400/16213e/ffffff?text=Galaxy+A55',''),
            ('iPhone 15 Pro Max','Apple','new',6499,'256GB','8GB','تيتانيوم','أقوى هاتف من آبل بشريحة A17 Pro','https://via.placeholder.com/300x400/0f3460/ffffff?text=iPhone+15+Pro',''),
            ('iPhone 14','Apple','like_new',3200,'128GB','6GB','أبيض','حالة ممتازة بدون خدوش','https://via.placeholder.com/300x400/533483/ffffff?text=iPhone+14',''),
            ('Realme GT 6','Realme','new',2199,'256GB','12GB','أخضر','معالج Snapdragon 8s Gen 3 بسعر منافس','https://via.placeholder.com/300x400/e94560/ffffff?text=Realme+GT6',''),
            ('Xiaomi 14','Xiaomi','new',3499,'512GB','16GB','أبيض','كاميرا Leica وشحن 90 واط','https://via.placeholder.com/300x400/1a1a2e/ffffff?text=Xiaomi+14',''),
            ('Samsung Galaxy S23','Samsung','like_new',2800,'256GB','8GB','كريمي','مستعمل استخدام خفيف جداً','https://via.placeholder.com/300x400/16213e/ffffff?text=Galaxy+S23',''),
            ('Oppo Reno 12','Oppo','new',1799,'128GB','8GB','أخضر','تصوير ليلي رائع وشحن سريع 80W','https://via.placeholder.com/300x400/0f3460/ffffff?text=Oppo+Reno12',''),
            ('iPhone 12','Apple','used',1600,'64GB','4GB','أسود','مستعمل بحالة جيدة، البطارية 85%','https://via.placeholder.com/300x400/533483/ffffff?text=iPhone+12',''),
            ('Realme C67','Realme','new',699,'128GB','6GB','أزرق','هاتف اقتصادي بأداء ممتاز','https://via.placeholder.com/300x400/e94560/ffffff?text=Realme+C67',''),
            ('Xiaomi Redmi Note 13','Xiaomi','new',899,'128GB','8GB','أسود','شاشة AMOLED وبطارية 5000 mAh','https://via.placeholder.com/300x400/1a1a2e/ffffff?text=Redmi+Note13',''),
            ('Samsung Galaxy A15','Samsung','used',550,'128GB','4GB','أزرق','مستعمل سنة، حالة كويسة','https://via.placeholder.com/300x400/16213e/ffffff?text=Galaxy+A15',''),
        ]
        conn.executemany(
            'INSERT INTO mobiles (name,brand,condition,price,storage,ram,color,description,image_url,youtube_url) VALUES (?,?,?,?,?,?,?,?,?,?)',
            samples
        )
    conn.commit()
    conn.close()

# ─── PUBLIC ──────────────────────────────────────────────────

@app.route('/')
def index():
    conn = get_db()
    condition_filter = request.args.get('condition', 'all')
    brand_filter     = request.args.get('brand', 'all')
    query  = 'SELECT * FROM mobiles WHERE 1=1'
    params = []
    if condition_filter != 'all':
        query += ' AND condition=?'; params.append(condition_filter)
    if brand_filter != 'all':
        query += ' AND brand=?';     params.append(brand_filter)
    query += ' ORDER BY created_at DESC'
    mobiles = conn.execute(query, params).fetchall()
    brands  = [r[0] for r in conn.execute('SELECT DISTINCT brand FROM mobiles ORDER BY brand').fetchall()]
    grouped = {}
    for m in conn.execute('SELECT * FROM mobiles ORDER BY condition, brand, name').fetchall():
        grouped.setdefault(m['condition'], {}).setdefault(m['brand'], []).append(m)
    conn.close()
    return render_template('index.html', mobiles=mobiles, grouped=grouped, brands=brands,
                           condition_filter=condition_filter, brand_filter=brand_filter,
                           whatsapp_num=WHATSAPP_NUM)

# ─── ADMIN ───────────────────────────────────────────────────

@app.route('/admin/<token>')
def admin(token):
    check_token(token)
    conn    = get_db()
    mobiles = conn.execute('SELECT * FROM mobiles ORDER BY created_at DESC').fetchall()
    sales   = conn.execute('SELECT * FROM sales ORDER BY sold_at DESC').fetchall()
    conn.close()
    return render_template('admin.html', mobiles=mobiles, sales=sales, token=token)

@app.route('/admin/<token>/add', methods=['GET','POST'])
def add_mobile(token):
    check_token(token)
    if request.method == 'POST':
        conn = get_db()
        conn.execute(
            'INSERT INTO mobiles (name,brand,condition,price,storage,ram,color,description,image_url,youtube_url) VALUES (?,?,?,?,?,?,?,?,?,?)',
            (request.form['name'], request.form['brand'], request.form['condition'],
             request.form['price'], request.form['storage'], request.form['ram'],
             request.form['color'], request.form['description'],
             request.form.get('image_url',''), request.form.get('youtube_url',''))
        )
        conn.commit(); conn.close()
        flash('تم إضافة الموبايل بنجاح! ✅','success')
        return redirect(url_for('admin', token=token))
    return render_template('add.html', token=token)

@app.route('/admin/<token>/edit/<int:id>', methods=['GET','POST'])
def edit_mobile(token, id):
    check_token(token)
    conn   = get_db()
    mobile = conn.execute('SELECT * FROM mobiles WHERE id=?', (id,)).fetchone()
    if not mobile: abort(404)
    if request.method == 'POST':
        conn.execute(
            'UPDATE mobiles SET name=?,brand=?,condition=?,price=?,storage=?,ram=?,color=?,description=?,image_url=?,youtube_url=? WHERE id=?',
            (request.form['name'], request.form['brand'], request.form['condition'],
             request.form['price'], request.form['storage'], request.form['ram'],
             request.form['color'], request.form['description'],
             request.form.get('image_url',''), request.form.get('youtube_url',''), id)
        )
        conn.commit(); conn.close()
        flash('تم تعديل الموبايل بنجاح! ✅','success')
        return redirect(url_for('admin', token=token))
    conn.close()
    return render_template('edit.html', mobile=mobile, token=token)

@app.route('/admin/<token>/delete/<int:id>', methods=['POST'])
def delete_mobile(token, id):
    check_token(token)
    conn = get_db()
    conn.execute('DELETE FROM mobiles WHERE id=?', (id,))
    conn.commit(); conn.close()
    flash('تم حذف الموبايل! 🗑️','success')
    return redirect(url_for('admin', token=token))

# ─── تسجيل بيع ───────────────────────────────────────────────

@app.route('/admin/<token>/sell/<int:id>', methods=['POST'])
def sell_mobile(token, id):
    check_token(token)
    conn   = get_db()
    mobile = conn.execute('SELECT * FROM mobiles WHERE id=?', (id,)).fetchone()
    if not mobile: abort(404)
    notes = request.form.get('notes', '')
    # سجّل في sales
    conn.execute(
        'INSERT INTO sales (mobile_id,name,brand,condition,price,notes) VALUES (?,?,?,?,?,?)',
        (mobile['id'], mobile['name'], mobile['brand'], mobile['condition'], mobile['price'], notes)
    )
    # احذفه من المخزون
    conn.execute('DELETE FROM mobiles WHERE id=?', (id,))
    conn.commit(); conn.close()
    flash(f'✅ تم تسجيل بيع «{mobile["name"]}» بنجاح وإزالته من المخزون!','success')
    return redirect(url_for('admin', token=token))

@app.route('/admin/<token>/sales/delete/<int:id>', methods=['POST'])
def delete_sale(token, id):
    check_token(token)
    conn = get_db()
    conn.execute('DELETE FROM sales WHERE id=?', (id,))
    conn.commit(); conn.close()
    flash('تم حذف السجل من التاريخ 🗑️','success')
    return redirect(url_for('admin', token=token) + '#history')

@app.route('/admin')
@app.route('/admin/')
def admin_bare():
    abort(404)

if __name__ == '__main__':
    init_db()
    app.run(debug=False)
