import os
from datetime import datetime
from smtplib import SMTP, SMTP_SSL

from flask import Flask, render_template, request, redirect, url_for, flash, session as flask_session
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from scraper import identify_platform, scrape_product
from models import Base, Product, PriceHistory, User, Watchlist, VisitHistory
import json
from sqlalchemy import text
from typing import Any
from bisect import bisect_left

try:
    from apscheduler.schedulers.background import BackgroundScheduler
except Exception:
    BackgroundScheduler = None


def get_env(name: str, default: str = ""):
    return os.environ.get(name, default)


# Auto-scrape interval configuration
AUTO_SCRAPE_MINUTES = int(get_env('AUTO_SCRAPE_MINUTES', '180'))


app = Flask(__name__, template_folder='templates', static_folder='.')
app.secret_key = get_env('SECRET_KEY', 'dev')

engine = create_engine('sqlite:///price_trak.db', future=True)

# Ensure tables exist
Base.metadata.create_all(engine)

# Ensure the users table has the 'matrix' column (2D-array stored as JSON text).
def ensure_user_matrix_column(engine):
    # SQLite: check pragma table_info using SQLAlchemy text()
    with engine.begin() as conn:
        res = conn.execute(text("PRAGMA table_info('users')"))
        cols = [r[1] for r in res.fetchall()]
        if 'matrix' not in cols:
            # add column if missing (use ALTER TABLE in a transaction)
            conn.execute(text("ALTER TABLE users ADD COLUMN matrix TEXT DEFAULT '[]'"))

ensure_user_matrix_column(engine)
def ensure_watchlist_seller_column(engine):
    # Ensure 'seller' column exists on watchlist table; add if missing
    with engine.begin() as conn:
        res = conn.execute(text("PRAGMA table_info('watchlist')"))
        cols = [r[1] for r in res.fetchall()]
        if 'seller' not in cols:
            conn.execute(text("ALTER TABLE watchlist ADD COLUMN seller TEXT"))

ensure_watchlist_seller_column(engine)
Session = sessionmaker(bind=engine)


def _normalize_text(val: Any):
    """Normalize a value that may be a BeautifulSoup Tag or other object into a stripped string or None."""
    if val is None:
        return None
    # BeautifulSoup Tag-like objects expose get_text
    get_text = getattr(val, 'get_text', None)
    if callable(get_text):
        try:
            txt = get_text(strip=True)
        except TypeError:
            txt = get_text()
        txt = txt.strip() if isinstance(txt, str) else None
        return txt if txt else None
    # fall back to str
    try:
        txt = str(val).strip()
    except Exception:
        return None
    return txt if txt else None


def current_user(db):
    uid = flask_session.get('uid')
    if not uid:
        return None
    user = db.query(User).get(uid)
    # if User model provides get_matrix helper, attach parsed matrix for convenience
    try:
        if user is not None and hasattr(user, 'get_matrix'):
            user.matrix_obj = user.get_matrix()
    except Exception:
        user.matrix_obj = None
    return user


def get_sorted_watchlist(db, user_id):
    items = db.query(Watchlist).join(Product).filter(Watchlist.user_id == user_id).order_by(Product.name.asc()).all()
    return items


def _watchlist_names(items):
    names = []
    for w in items:
        name = None
        try:
            name = (w.product.name or '').lower()
        except Exception:
            name = ''
        names.append(name)
    return names


def is_in_watchlist(db, user_id, product_id, product_name):
    items = get_sorted_watchlist(db, user_id)
    names = _watchlist_names(items)
    key = (product_name or '').lower()
    i = bisect_left(names, key)
    if i != len(names) and names[i] == key:
        # double check product_id match
        return any(w.product_id == product_id for w in items if (w.product.name or '').lower() == key)
    return False


def insert_watchlist(db, user_id, product):
    items = get_sorted_watchlist(db, user_id)
    names = _watchlist_names(items)
    key = (product.name or '').lower()
    i = bisect_left(names, key)
    if i != len(names) and names[i] == key:
        for w in items:
            if w.product_id == product.id:
                return False
    w = Watchlist(user_id=user_id, product_id=product.id, last_notified_price=product.last_price, seller=product.seller)
    db.add(w)
    db.commit()
    return True


def remove_watchlist(db, user_id, product):
    items = get_sorted_watchlist(db, user_id)
    names = _watchlist_names(items)
    key = (product.name or '').lower()
    i = bisect_left(names, key)
    if i == len(names) or names[i] != key:
        return False
    for w in items:
        if w.product_id == product.id:
            db.delete(w)
            db.commit()
            return True
    return False


@app.route('/')
def index():
    db = Session()
    user = current_user(db)
    return render_template('index.html', user=user)


@app.route('/signup')
def signup_page():
    db = Session()
    user = current_user(db)
    if user:
        return redirect(url_for('dashboard'))
    return render_template('signup.html', user=None)


@app.route('/register', methods=['POST'])
def register():
    db = Session()
    email = request.form.get('email', '').strip().lower()
    username = request.form.get('username', '').strip()
    password = request.form.get('password', '')
    if not email or not username or not password:
        flash('All fields are required!', "danger")
        return redirect(url_for('index'))
    if db.query(User).filter((User.email == email) | (User.username == username)).first():
        flash('Email or username already in use!', 'danger')
        return redirect(url_for('signup_page'))
    initial_matrix = json.dumps([[username, generate_password_hash(password)]])
    user = User(email=email, username=username, password_hash=generate_password_hash(password), matrix=initial_matrix)
    db.add(user)
    db.commit()
    flask_session['uid'] = user.id
    flash(f'Account created successfully! Welcome to PriceTrak, {username}.', "success")
    return redirect(url_for('dashboard'))


@app.route('/login', methods=['GET'])
def login_page():
    db = Session()
    user = current_user(db)
    if user:
        return redirect(url_for('dashboard'))
    return render_template('login.html', user=None)


@app.route('/login', methods=['POST'])
def login():
    db = Session()
    email_or_username = request.form.get('email_or_username', '').strip().lower()
    password = request.form.get('password', '')
    user = db.query(User).filter((User.email == email_or_username) | (User.username == email_or_username)).first()
    if not user or not check_password_hash(user.password_hash, password):
        flash('Invalid credentials!', "danger")
        return redirect(url_for('login_page'))
    flask_session['uid'] = user.id
    flash(f'Logged in! Welcome to PriceTrak, {user.username}.', "success")
    return redirect(url_for('dashboard'))


@app.route('/logout')
def logout():
    flask_session.pop('uid', None)
    flash('Logged out successfully!', "success")
    return redirect(url_for('index'))


@app.route('/dashboard')
def dashboard():
    db = Session()
    user = current_user(db)
    if not user:
        return redirect(url_for('login_page'))
    # get recent visit history for the user
    visits = db.query(VisitHistory).filter_by(user_id=user.id).order_by(VisitHistory.created_at.desc()).limit(100).all()
    return render_template('dashboard.html', user=user, visits=visits)


@app.route('/track', methods=['POST'])
def track():
    url = request.form['url'].strip()
    platform = identify_platform(url)
    if not platform:
        flash('Unsupported or invalid URL! Please try inputting a valid Amazon or Lazada URL.', "danger")
        return redirect(url_for('index'))
    data = scrape_product(url, platform)
    data['currency'] = 'PHP'
    db = Session()
    product = db.query(Product).filter_by(platform=platform, platform_product_id=data['platform_product_id']).first()
    if not product:
        seller_val = _normalize_text(data.get('seller'))
        name_val = _normalize_text(data.get('name')) or data.get('platform_product_id')
        product = Product(
            platform=platform,
            platform_product_id=data['platform_product_id'],
            name=name_val,
            seller=seller_val,
            last_price=data['price'],
            currency='PHP',
            url=data['url'],
            last_checked_at=datetime.now(),
        )
        db.add(product)
        db.commit()
    else:
        # update seller/name if provided as primitive text
        seller_val = _normalize_text(data.get('seller'))
        name_val = _normalize_text(data.get('name'))
        if seller_val:
            product.seller = seller_val
        if name_val:
            product.name = name_val
    ph = PriceHistory(product_id=product.id, price=data['price'], currency='PHP')
    product.last_price = data['price']
    product.currency = 'PHP'
    product.last_checked_at = datetime.now()
    db.add(ph)
    db.commit()
    user = current_user(db)
    # record visit history for signed-in users
    if user:
        try:
            vh = VisitHistory(user_id=user.id, name=product.name or '', url=product.url or '', price=product.last_price, currency=product.currency)
            db.add(vh)
            db.commit()
        except Exception:
            db.rollback()
    # set is_watched flag for template
    is_watched = False
    if user:
        is_watched = db.query(Watchlist).filter_by(user_id=user.id, product_id=product.id).first() is not None
    # pass is_watched attribute to product object for template compatibility
    product.is_watched = is_watched
    # record view in VisitHistory for signed-in users
    if user and product:
        try:
            vh = VisitHistory(user_id=user.id, name=product.name or '', url=product.url or '', price=product.last_price, currency=product.currency)
            db.add(vh)
            db.commit()
        except Exception:
            db.rollback()
    return render_template('product.html', product=product, user=user)


@app.route('/product/<int:product_id>')
def product_view(product_id):
    db = Session()
    product = db.query(Product).get(product_id)
    user = current_user(db)
    # compute watch status for this user
    is_watched = False
    if user:
        is_watched = db.query(Watchlist).filter_by(user_id=user.id, product_id=product.id).first() is not None
    product.is_watched = is_watched
    return render_template('product.html', product=product, user=user)


@app.route('/watch/<int:product_id>', methods=['POST'])
def add_watch(product_id):
    db = Session()
    user = current_user(db)
    if not user:
        flash('Please log in to use the watchlist!', "warning")
        return redirect(url_for('product_view', product_id=product_id))
    product = db.query(Product).get(product_id)
    if not product:
        flash('Product not found!', "danger")
        return redirect(url_for('index'))
    inserted = insert_watchlist(db, user.id, product)
    if inserted:
        flash('Added to watchlist!', "success")
    else:
        flash('Already in watchlist!', "warning")
    return redirect(url_for('watchlist'))


@app.route('/unwatch/<int:product_id>', methods=['POST'])
def remove_watch(product_id):
    db = Session()
    user = current_user(db)
    if not user:
        flash('Please log in!', "warning")
        return redirect(url_for('index'))
    product = db.query(Product).get(product_id)
    if not product:
        flash('Product not found!', "danger")
        return redirect(url_for('watchlist'))
    removed = remove_watchlist(db, user.id, product)
    if removed:
        flash('Removed from watchlist!', "success")
    else:
        flash('Item not in your watchlist!', "warning")
    return redirect(url_for('watchlist'))


@app.route('/watchlist')
def watchlist():
    db = Session()
    user = current_user(db)
    if not user:
        flash('Please log in!', "warning")
        return redirect(url_for('login_page'))
    # return watchlist sorted by product name
    items = get_sorted_watchlist(db, user.id)
    return render_template('watchlist.html', items=items, user=user)


def send_email(to_email: str, subject: str, body: str):
    host = get_env('SMTP_HOST')
    port = int(get_env('SMTP_PORT', '465'))
    user = get_env('SMTP_USER')
    pwd = get_env('SMTP_PASS')
    if not host or not user or not pwd:
        print("Email not configured.")
        return  # email not configured
    message = f"From: PriceTrak <{user}>\r\nTo: <{to_email}>\r\nSubject: {subject}\r\n\r\n{body}"
    try:
        with SMTP_SSL(host, port) as smtp:
            smtp.login(user, pwd)
            smtp.sendmail(user, [to_email], message)
    except Exception:
        pass


def refresh_prices_and_notify():
    print(f"\n[AUTO_SCRAPE] Starting auto-scrape of watchlisted items at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    db = Session()
    # Get unique watchlisted products
    product_ids = {w.product_id for w in db.query(Watchlist).all()}
    
    if not product_ids:
        print("[AUTO_SCRAPE] No watchlisted products found.")
        return
    
    print(f"[AUTO_SCRAPE] Found {len(product_ids)} unique product(s) in watchlist.")
    
    scraped_count = 0
    for pid in product_ids:
        product = db.query(Product).get(pid)
        if not product:
            continue
        try:
            print(f"  [AUTO_SCRAPE] Scraping: {product.name} ({product.platform})")
            data = scrape_product(product.url, product.platform)
        except Exception:
            print(f"  [AUTO_SCRAPE] ⚠️  Failed to scrape: {product.name}")
            continue
        
        scraped_count += 1
        old_price = product.last_price or 0.0
        new_price = data.get('price') or old_price
        product.last_price = new_price
        product.last_checked_at = datetime.now()
        db.add(PriceHistory(product_id=product.id, price=new_price, currency=product.currency))
        db.commit()
        
        print(f"    ✓ Price: {product.currency} {new_price} (was {old_price})")

        if new_price < old_price:
            # Notify each watcher
            watchers = db.query(Watchlist).filter_by(product_id=product.id).all()
            for w in watchers:
                user = db.query(User).get(w.user_id)
                if not user:
                    continue
                if new_price < old_price and w.notify_price_drop:
                    send_email(
                        to_email=user.email,
                        subject=f"Price drop: {product.name}",
                        body=(
                            f"Good news! The price for '{product.name}' dropped from {old_price} to {new_price}.\n"
                            f"Link: {product.url}"
                        ),
                    )
                    w.last_notified_price = new_price
            db.commit()
    
    print(f"[AUTO_SCRAPE] Completed: {scraped_count}/{len(product_ids)} products scraped successfully.\n")


if BackgroundScheduler is not None:
    scheduler = BackgroundScheduler(daemon=True)
    scheduler.add_job(refresh_prices_and_notify, 'interval', minutes=AUTO_SCRAPE_MINUTES, id='refresh_job', replace_existing=True)
    print(f"[SCHEDULER] Auto-scrape job scheduled every {AUTO_SCRAPE_MINUTES} minute(s).")
    try:
        scheduler.start()
        print("[SCHEDULER] Background scheduler started.")
    except Exception:
        print("[SCHEDULER] Failed to start background scheduler.")
        pass


if __name__ == '__main__':
    app.run(debug=True)