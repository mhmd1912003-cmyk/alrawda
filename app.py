from flask import Flask, render_template, request, redirect, url_for, flash, abort, send_from_directory
import sqlite3, os, urllib.parse, uuid, json
from werkzeug.utils import secure_filename
from PIL import Image, ImageOps

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'rawda-secret-2024')

ADMIN_TOKEN   = os.environ.get('ADMIN_TOKEN', 'rawda2024xK9')
WHATSAPP_NUM  = os.environ.get('WHATSAPP_NUM', '201000000000')

DB_PATH        = os.path.join(os.path.dirname(__file__), 'rawda.db')
UPLOAD_FOLDER  = os.path.join(os.path.dirname(__file__), 'uploads')
THUMBS_FOLDER  = os.path.join(UPLOAD_FOLDER, 'thumbs')
ALLOWED_EXTS   = {'png', 'jpg', 'jpeg', 'gif', 'webp'}

# Max dimensions used when resizing uploaded photos. Phone camera photos can be
# 4000x3000+ and several MB each; there's no reason to ship that much data to
# a card that renders at ~200px tall. These caps are what actually fix the
# "images take forever to load" problem.
FULL_MAX_DIM  = 1600   # used for the modal / full-size view
THUMB_MAX_DIM = 480    # used for the grid cards
FULL_QUALITY  = 82
THUMB_QUALITY = 72

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(THUMBS_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 40 * 1024 * 1024  # 40MB

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTS

def _resize_to_max(img, max_dim):
    w, h = img.size
    if max(w, h) <= max_dim:
        return img
    if w >= h:
        new_w, new_h = max_dim, round(h * max_dim / w)
    else:
        new_h, new_w = max_dim, round(w * max_dim / h)
    return img.resize((new_w, new_h), Image.LANCZOS)

def _make_thumb_from_full(full_path, thumb_path):
    """Build a small compressed WEBP thumbnail from an already-saved full image."""
    with Image.open(full_path) as img:
        img = ImageOps.exif_transpose(img)
        if img.mode not in ('RGB', 'RGBA'):
            img = img.convert('RGB')
        thumb = _resize_to_max(img, THUMB_MAX_DIM)
        thumb.save(thumb_path, 'WEBP', quality=THUMB_QUALITY, method=6)

def save_uploaded_images(files):
    """Save uploaded images, compressing/resizing them and generating a
    matching small thumbnail so the grid view doesn't have to load full-size
    camera photos."""
    saved = []
    for f in files:
        if not (f and f.filename and allowed_file(f.filename)):
            continue
        ext = f.filename.rsplit('.', 1)[1].lower()
        base = uuid.uuid4().hex

        if ext == 'gif':
            # Animated GIFs: keep as-is (resizing/re-encoding would lose the
            # animation), just save and use the same file as its own thumb.
            fname = f"{base}.gif"
            full_path = os.path.join(UPLOAD_FOLDER, fname)
            f.save(full_path)
            thumb_path = os.path.join(THUMBS_FOLDER, fname)
            try:
                import shutil
                shutil.copyfile(full_path, thumb_path)
            except Exception:
                pass
            saved.append(f"/uploads/{fname}")
            continue

        try:
            img = Image.open(f.stream)
            img = ImageOps.exif_transpose(img)  # respect camera orientation
            if img.mode not in ('RGB', 'RGBA'):
                img = img.convert('RGB')

            fname = f"{base}.webp"
            full_path = os.path.join(UPLOAD_FOLDER, fname)
            full_img = _resize_to_max(img, FULL_MAX_DIM)
            full_img.save(full_path, 'WEBP', quality=FULL_QUALITY, method=6)

            thumb_path = os.path.join(THUMBS_FOLDER, fname)
            thumb_img = _resize_to_max(img, THUMB_MAX_DIM)
            thumb_img.save(thumb_path, 'WEBP', quality=THUMB_QUALITY, method=6)

            saved.append(f"/uploads/{fname}")
        except Exception:
            # Fallback: if Pillow can't read it for some reason, save the raw file
            fname = f"{base}.{ext}"
            f.stream.seek(0)
            f.save(os.path.join(UPLOAD_FOLDER, fname))
            saved.append(f"/uploads/{fname}")
    return saved

@app.route('/uploads/thumb/<filename>')
def uploaded_thumb(filename):
    """Serve a small thumbnail. If one doesn't exist yet (e.g. images
    uploaded before this optimization was added), generate it on the fly
    from the original and cache it for next time."""
    thumb_path = os.path.join(THUMBS_FOLDER, filename)
    if not os.path.exists(thumb_path):
        orig_path = os.path.join(UPLOAD_FOLDER, filename)
        if os.path.exists(orig_path):
            try:
                _make_thumb_from_full(orig_path, thumb_path)
            except Exception:
                abort(404)
        else:
            abort(404)
    return send_from_directory(THUMBS_FOLDER, filename, max_age=60 * 60 * 24 * 30)

@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(UPLOAD_FOLDER, filename, max_age=60 * 60 * 24 * 30)

@app.template_filter('thumb')
def thumb_filter(path):
    """Convert an /uploads/xxx path to its small thumbnail equivalent for use
    in the grid view. External URLs (e.g. placeholder images) pass through."""
    if not path or not path.startswith('/uploads/') or path.startswith('/uploads/thumb/'):
        return path
    filename = path.rsplit('/', 1)[-1]
    return f'/uploads/thumb/{filename}'

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def check_token(token):
    if token != ADMIN_TOKEN:
        abort(404)

def init_db():
    conn = get_db()
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
            images_json TEXT,
            youtube_url TEXT,
            created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    for col_def in ['youtube_url TEXT', 'images_json TEXT']:
        try:
            conn.execute(f'ALTER TABLE mobiles ADD COLUMN {col_def}')
        except Exception:
            pass

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
            ('Samsung Galaxy S24 Ultra','Samsung','new',4999,'256GB','12GB','أسود','هاتف رائد بكاميرا 200 ميجابكسل وقلم S Pen','https://via.placeholder.com/400x500/1a1a2e/ffffff?text=S24+Ultra','[]',''),
            ('iPhone 15 Pro Max','Apple','new',6499,'256GB','8GB','تيتانيوم','أقوى هاتف من آبل بشريحة A17 Pro','https://via.placeholder.com/400x500/0f3460/ffffff?text=iPhone+15+Pro','[]',''),
            ('Realme GT 6','Realme','new',2199,'256GB','12GB','أخضر','معالج Snapdragon 8s Gen 3 بسعر منافس','https://via.placeholder.com/400x500/e94560/ffffff?text=Realme+GT6','[]',''),
            ('iPhone 14','Apple','like_new',3200,'128GB','6GB','أبيض','حالة ممتازة بدون خدوش','https://via.placeholder.com/400x500/533483/ffffff?text=iPhone+14','[]',''),
            ('Samsung Galaxy S23','Samsung','like_new',2800,'256GB','8GB','كريمي','مستعمل استخدام خفيف جداً','https://via.placeholder.com/400x500/16213e/ffffff?text=Galaxy+S23','[]',''),
            ('iPhone 12','Apple','used',1600,'64GB','4GB','أسود','مستعمل بحالة جيدة، البطارية 85%','https://via.placeholder.com/400x500/533483/ffffff?text=iPhone+12','[]',''),
        ]
        conn.executemany(
            'INSERT INTO mobiles (name,brand,condition,price,storage,ram,color,description,image_url,images_json,youtube_url) VALUES (?,?,?,?,?,?,?,?,?,?,?)',
            samples
        )
    conn.commit()
    conn.close()

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
        uploaded_files = request.files.getlist('images')
        image_paths = save_uploaded_images(uploaded_files)
        primary_image = image_paths[0] if image_paths else ''
        images_json_str = json.dumps(image_paths)

        conn = get_db()
        conn.execute(
            'INSERT INTO mobiles (name,brand,condition,price,storage,ram,color,description,image_url,images_json,youtube_url) VALUES (?,?,?,?,?,?,?,?,?,?,?)',
            (request.form['name'], request.form['brand'], request.form['condition'],
             request.form['price'], request.form['storage'], request.form['ram'],
             request.form['color'], request.form['description'],
             primary_image, images_json_str, request.form.get('youtube_url',''))
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
        uploaded_files = request.files.getlist('images')
        new_paths = save_uploaded_images(uploaded_files)
        kept_images = request.form.getlist('keep_images')
        all_images = kept_images + new_paths
        images_json_str = json.dumps(all_images)
        primary_image = all_images[0] if all_images else ''

        conn.execute(
            'UPDATE mobiles SET name=?,brand=?,condition=?,price=?,storage=?,ram=?,color=?,description=?,image_url=?,images_json=?,youtube_url=? WHERE id=?',
            (request.form['name'], request.form['brand'], request.form['condition'],
             request.form['price'], request.form['storage'], request.form['ram'],
             request.form['color'], request.form['description'],
             primary_image, images_json_str, request.form.get('youtube_url',''), id)
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

@app.route('/admin/<token>/sell/<int:id>', methods=['POST'])
def sell_mobile(token, id):
    check_token(token)
    conn   = get_db()
    mobile = conn.execute('SELECT * FROM mobiles WHERE id=?', (id,)).fetchone()
    if not mobile: abort(404)
    notes = request.form.get('notes', '')
    conn.execute(
        'INSERT INTO sales (mobile_id,name,brand,condition,price,notes) VALUES (?,?,?,?,?,?)',
        (mobile['id'], mobile['name'], mobile['brand'], mobile['condition'], mobile['price'], notes)
    )
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

# ─── Jinja2 filters ───────────────────────────────────────────
@app.template_filter('fromjson')
def fromjson_filter(s):
    try:
        return json.loads(s) if s else []
    except Exception:
        return []

with app.app_context():
    init_db()

if __name__ == '__main__':
    app.run(debug=False)
