from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify, make_response
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import MetaData
from flask_migrate import Migrate
from flask_wtf import FlaskForm
from wtforms import StringField, FloatField, IntegerField, TextAreaField, SubmitField, SelectField, PasswordField
from wtforms.validators import DataRequired, Email, NumberRange, Length, EqualTo, ValidationError
from models import db, Product, Command, CommandItem, User, Address, Wishlist
from flask_mail import Mail, Message
import secrets
from datetime import datetime
import os
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from PIL import Image
from functools import wraps
from fapshi import FapshiClient
from sqlalchemy import text, or_
import csv
import io
from dotenv import load_dotenv
#import re
load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY")

fapshi = FapshiClient(
    api_user=os.getenv("FAPSHI_API_USER"),
    api_key=os.getenv("FAPSHI_API_KEY")
)
if not os.getenv("FAPSHI_API_USER") or not os.getenv("FAPSHI_API_KEY"):
    raise RuntimeError("FAPSHI_API_USER and FAPSHI_API_KEY must be set.")

app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', secrets.token_hex(32))
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('SQLALCHEMY_DATABASE_URI', 'sqlite:///shopMetuge.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = os.environ.get('SQLALCHEMY_TRACK_MODIFICATIONS', 'False') == 'True'
app.config['ADMIN_CODE'] = os.environ.get('ADMIN_CODE', 'ADMIN123')
app.config['UPLOAD_FOLDER'] = os.environ.get('UPLOAD_FOLDER', os.path.join('static', 'uploads'))
app.config['MAX_IMAGE_SIZE'] = (int(os.environ.get('MAX_IMAGE_SIZE', 800)), int(os.environ.get('MAX_IMAGE_SIZE', 800)))
'''
# Email Configuration (Gmail with App Password)
app.config['MAIL_SERVER'] = os.environ.get('MAIL_SERVER', 'smtp.gmail.com')
app.config['MAIL_PORT'] = int(os.environ.get('MAIL_PORT', 587))
app.config['MAIL_USE_TLS'] = os.environ.get('MAIL_USE_TLS', 'True') == 'True'
app.config['MAIL_USERNAME'] = os.environ.get('MAIL_USERNAME')  # your gmail address
app.config['MAIL_PASSWORD'] = os.environ.get('MAIL_PASSWORD')  # app-specific password
app.config['MAIL_DEFAULT_SENDER'] = os.environ.get('MAIL_DEFAULT_SENDER', 'support@shopmetuge.com')
'''
if os.environ.get('FLASK_DEBUG', 'False') == 'True':
    app.config['MAIL_SUPPRESS_SEND'] = True

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

# Initialize database and mail
db.init_app(app)
mail = Mail(app)
migrate = Migrate(app, db)
migrate = Migrate(app, db, render_as_batch=True)
convention = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s"
}

#db = SQLAlchemy(metadata=MetaData(naming_convention=convention))

# ensure upload folder exists
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def save_image(file_storage, base_name=None):
    if not file_storage or file_storage.filename == '' or not allowed_file(file_storage.filename):
        return None
    filename = secure_filename(file_storage.filename)
    name, ext = os.path.splitext(filename)
    # use provided base_name if given
    base = secure_filename(base_name) if base_name else name

    # define target filenames for sizes
    main_fname = f"{base}{ext}"
    med_fname = f"{base}_med{ext}"
    thumb_fname = f"{base}_thumb{ext}"

    main_path = os.path.join(app.config['UPLOAD_FOLDER'], main_fname)
    med_path = os.path.join(app.config['UPLOAD_FOLDER'], med_fname)
    thumb_path = os.path.join(app.config['UPLOAD_FOLDER'], thumb_fname)

    # Save original upload to main_path then create resized versions
    file_storage.save(main_path)
    try:
        img = Image.open(main_path)
        img = img.convert('RGB')

        # main (constrained to MAX_IMAGE_SIZE)
        main_img = img.copy()
        main_img.thumbnail(app.config['MAX_IMAGE_SIZE'], Image.Resampling.LANCZOS)
        main_img.save(main_path, quality=85, optimize=True)

        # medium (e.g., 400x400)
        med_img = img.copy()
        med_img.thumbnail((400, 400), Image.Resampling.LANCZOS)
        med_img.save(med_path, quality=85, optimize=True)

        # thumbnail (e.g., 200x200)
        thumb_img = img.copy()
        thumb_img.thumbnail((200, 200), Image.Resampling.LANCZOS)
        thumb_img.save(thumb_path, quality=85, optimize=True)
    except Exception as e:
        print(f"Image processing error: {e}")
        # fallback: ensure at least main file exists
        pass

    # Return base filename (used to build srcset in templates)
    return f"/static/uploads/{base}{ext}"

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if session.get('role') != 'admin':
            flash('Admin access required.', 'warning')
            return redirect(url_for('admin_login'))
        return f(*args, **kwargs)
    return decorated

@app.template_filter('fcfa')
def format_fcfa(value):
    try:
        v = float(value)
    except Exception:
        return value
    # Format without decimals and use non-breaking space as thousands separator
    formatted = "{:,.0f}".format(v).replace(',', '\u00A0')
    return formatted

# Forms
class ProductForm(FlaskForm):
    name = StringField('Product Name', validators=[DataRequired()])
    description = TextAreaField('Description')
    price = FloatField('Price', validators=[DataRequired(), NumberRange(min=0)])
    quantity = IntegerField('Quantity', validators=[NumberRange(min=0)])
    image_url = StringField('Image URL')
    # avoid naming this field 'submit' which would shadow the form.submit() method in JS
    submit_btn = SubmitField('Add Product')

class CheckoutForm(FlaskForm):
    customer_name = StringField('Full Name', validators=[DataRequired()])
    customer_email = StringField('Email', validators=[DataRequired(), Email()])
    customer_address = TextAreaField('Shipping Address', validators=[DataRequired()])
    payment_method = SelectField('Payment Method', choices=[('mtn','MTN Mobile Money'), ('orange','ORANGE Money'), ('cash','Cash')], validators=[DataRequired()])
    transaction_reference = StringField('Transaction ID / Reference')
    submit = SubmitField('Place Order')

class ContactForm(FlaskForm):
    name = StringField('Your Name', validators=[DataRequired()])
    email = StringField('Your Email', validators=[DataRequired(), Email()])
    subject = StringField('Subject', validators=[DataRequired()])
    message = TextAreaField('Message', validators=[DataRequired()])
    submit = SubmitField('Send Message')

class ChangePasswordForm(FlaskForm):
    current_password = PasswordField('Current Password', validators=[DataRequired()])
    new_password = PasswordField('New Password', validators=[
        DataRequired(),
        Length(min=8, message='Password must be at least 8 characters long'),
        EqualTo('confirm_password', message='Passwords must match')
    ])
    confirm_password = PasswordField('Confirm New Password', validators=[DataRequired()])
    submit = SubmitField('Change Password')

    def validate_new_password(self, field):
        # Check for password strength
        if not re.search(r'[A-Z]', field.data):
            raise ValidationError('Password must contain at least one uppercase letter')
        if not re.search(r'[a-z]', field.data):
            raise ValidationError('Password must contain at least one lowercase letter')
        if not re.search(r'[0-9]', field.data):
            raise ValidationError('Password must contain at least one number')
        if not re.search(r'[!@#$%^&*(),.?":{}|<>]', field.data):
            raise ValidationError('Password must contain at least one special character')

class AdminPasswordResetForm(FlaskForm):
    admin_code = StringField('Admin Code', validators=[DataRequired()])
    new_password = PasswordField('New Admin Password', validators=[
        DataRequired(),
        Length(min=8, message='Password must be at least 8 characters long'),
        EqualTo('confirm_password', message='Passwords must match')
    ])
    confirm_password = PasswordField('Confirm New Password', validators=[DataRequired()])
    submit = SubmitField('Reset Admin Password')

# Routes
@app.route('/')
def index():
    # show active products on the home page oldest-first so new items appear last
    products = Product.query.filter(Product.is_active == True).order_by(Product.created_at.asc()).limit(20).all()
    return render_template('index.html', products=products)

@app.route("/products")
def products():
    # Get filter inputs from query string
    q         = request.args.get("q", "").strip()
    min_price = request.args.get("min_price", type=float)
    max_price = request.args.get("max_price", type=float)
    sort      = request.args.get("sort", "")
    page      = request.args.get("page", 1, type=int)
    per_page  = 12  # products per page

    # Build the base query
    query = Product.query

    # Apply search filter
    if q:
        like = f"%{q}%"
        query = query.filter(
            db.or_(
                Product.name.ilike(like),
                Product.description.ilike(like)
            )
        )

    # Apply price filters
    if min_price is not None:
        query = query.filter(Product.price >= min_price)
    if max_price is not None:
        query = query.filter(Product.price <= max_price)

    # Apply sorting
    if sort == "price_asc":
        query = query.order_by(Product.price.asc())
    elif sort == "price_desc":
        query = query.order_by(Product.price.desc())
    else:
        query = query.order_by(Product.created_at.desc())

    # Paginate
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    products = pagination.items

    return render_template(
        "products.html",
        products=products,
        pagination=pagination,
        q=q,
        min_price=min_price,
        max_price=max_price,
        sort=sort
    )

@app.route('/admin')
@admin_required
def admin_dashboard():
    total_products = Product.query.count()
    total_orders = Command.query.count()
    pending_orders = Command.query.filter_by(status='pending').count()
    completed_orders = Command.query.filter_by(status='delivered').count()

    # Calculate total revenue
    total_revenue = db.session.query(db.func.sum(Command.total_amount)).scalar() or 0

    # Get recent orders
    recent_orders = Command.query.order_by(Command.created_at.desc()).limit(5).all()

    # Get low stock products
    low_stock_products = Product.query.filter(Product.quantity < 10).limit(5).all()

    return render_template('admin.html',
                         total_products=total_products,
                         total_orders=total_orders,
                         pending_orders=pending_orders,
                         completed_orders=completed_orders,
                         total_revenue=total_revenue,
                         recent_orders=recent_orders,
                         low_stock_products=low_stock_products)

@app.route('/admin/change-password', methods=['GET', 'POST'])
@admin_required
def admin_change_password():
    form = ChangePasswordForm()
    user = User.query.get(session['user_id'])
    
    if form.validate_on_submit():
        if user.check_password(form.current_password.data):
            user.set_password(form.new_password.data)
            try:
                db.session.commit()
                flash('Your password has been changed successfully!', 'success')
                return redirect(url_for('admin_dashboard'))
            except Exception as e:
                db.session.rollback()
                flash(f'Error changing password: {str(e)}', 'danger')
        else:
            flash('Current password is incorrect.', 'danger')
    
    return render_template('admin_change_password.html', form=form)

@app.route('/admin/reset-password', methods=['GET', 'POST'])
def admin_reset_password():
    form = AdminPasswordResetForm()
    
    if form.validate_on_submit():
        if form.admin_code.data == app.config['ADMIN_CODE']:
            # Find admin user(s) and reset password
            admin_users = User.query.filter_by(role='admin').all()
            if admin_users:
                for admin in admin_users:
                    admin.set_password(form.new_password.data)
                try:
                    db.session.commit()
                    flash('Admin password has been reset successfully! Please login with your new password.', 'success')
                    return redirect(url_for('admin_login'))
                except Exception as e:
                    db.session.rollback()
                    flash(f'Error resetting password: {str(e)}', 'danger')
            else:
                flash('No admin users found. Please contact system administrator.', 'warning')
        else:
            flash('Invalid admin code.', 'danger')
    
    return render_template('admin_reset_password.html', form=form)

@app.route('/product/<int:id>')
def product_detail(id):
    product = Product.query.get_or_404(id)
    # Get related products (same category or similar price range)
    related_products = Product.query.filter(
        Product.is_active == True,
        Product.id != product.id
    ).order_by(db.func.random()).limit(4).all()
    return render_template('product_detail.html', product=product, related_products=related_products)

@app.route('/add_to_cart/<int:product_id>')
def add_to_cart(product_id):
    product = Product.query.get_or_404(product_id)
    
    if product.quantity < 1:
        flash(f'Sorry, {product.name} is out of stock!', 'warning')
        return redirect(request.referrer or url_for('products'))
    
    # Initialize cart in session if not exists
    if 'cart' not in session:
        session['cart'] = {}
    
    cart = session['cart']
    product_id_str = str(product_id)
    
    if product_id_str in cart:
        if cart[product_id_str]['quantity'] < product.quantity:
            cart[product_id_str]['quantity'] += 1
        else:
            flash(f'Sorry, only {product.quantity} items available!', 'warning')
            return redirect(request.referrer or url_for('products'))
    else:
        cart[product_id_str] = {
            'name': product.name,
            'price': float(product.price),
            'quantity': 1,
            'image': product.image_url,
            'max_quantity': product.quantity
        }
    
    session['cart'] = cart
    flash(f'{product.name} added to cart!', 'success')
    return redirect(request.referrer or url_for('products'))

@app.route('/update_cart/<int:product_id>', methods=['POST'])
def update_cart(product_id):
    product = Product.query.get_or_404(product_id)
    quantity = int(request.form.get('quantity', 1))
    
    cart = session.get('cart', {})
    product_id_str = str(product_id)
    
    if product_id_str in cart:
        if quantity <= 0:
            # Remove item
            del cart[product_id_str]
            flash('Item removed from cart!', 'info')
        elif quantity <= product.quantity:
            cart[product_id_str]['quantity'] = quantity
            flash('Cart updated!', 'success')
        else:
            flash(f'Sorry, only {product.quantity} items available!', 'warning')
    
    session['cart'] = cart
    return redirect(url_for('cart'))

@app.route('/cart')
def cart():
    cart_items = session.get('cart', {})
    total = 0
    item_count = 0
    
    # Validate cart items against database
    valid_cart = {}
    for product_id_str, item in cart_items.items():
        product = Product.query.get(int(product_id_str))
        if product and product.is_active:
            valid_cart[product_id_str] = item
            total += item['price'] * item['quantity']
            item_count += item['quantity']
        else:
            flash(f'{item["name"]} is no longer available and has been removed from your cart.', 'warning')
    
    session['cart'] = valid_cart
    
    return render_template('cart.html', cart=valid_cart, total=total, item_count=item_count)

@app.route('/remove_from_cart/<product_id>')
def remove_from_cart(product_id):
    cart = session.get('cart', {})
    if product_id in cart:
        product_name = cart[product_id]['name']
        del cart[product_id]
        session['cart'] = cart
        flash(f'{product_name} removed from cart!', 'info')
    return redirect(url_for('cart'))

@app.route("/checkout", methods=["GET", "POST"])
def checkout():
    cart = session.get("cart", {})
    if not cart:
        flash("Your cart is empty.", "warning")
        return redirect(url_for("products"))

    subtotal = sum(item["price"] * item["quantity"] for item in cart.values())
    delivery_fee = 2000
    total_amount = subtotal + delivery_fee

    if request.method == "POST":
        import random
        command_number = f"CMD-{random.randint(100000, 999999)}"

        new_command = Command(
            command_number=command_number,
            customer_name=request.form["customer_name"],
            customer_email=request.form["customer_email"],
            customer_address=request.form["customer_address"],
            payment_method=request.form["payment_method"],
            total_amount=total_amount,
            status="pending"
        )
        db.session.add(new_command)
        db.session.flush()

        for product_id_str, item in cart.items():
            product = Product.query.get(int(product_id_str))
            if not product or product.quantity < item["quantity"]:
                flash(f"Insufficient stock for {item['name']}.", "danger")
                db.session.rollback()
                return redirect(url_for("cart"))

            command_item = CommandItem(
                command_id=new_command.id,
                product_id=product.id,
                quantity=item["quantity"],
                price_at_time=item["price"]
            )
            db.session.add(command_item)
            product.quantity -= item["quantity"]

        db.session.commit()

        try:
            response = fapshi.initiate_pay(
                amount=int(total_amount),
                email=new_command.customer_email,
                redirect_url=url_for("payment_callback", _external=True),
                external_id=str(new_command.id),
                message=f"Linux Shop — Order {new_command.command_number}"
            )
            new_command.fapshi_trans_id = response["transId"]
            db.session.commit()
            return redirect(response["link"])

        except Exception as e:
            db.session.rollback()
            flash(f"Payment could not be started: {e}", "danger")
            return redirect(url_for("checkout"))

    # GET — no `form=form` here
    return render_template(
        "checkout.html",
        cart=cart,
        subtotal=subtotal,
        delivery_fee=delivery_fee,
        total_amount=total_amount
    )

'''
@app.route('/checkout', methods=['GET', 'POST'])
def checkout():
    form = CheckoutForm()
    cart_items = session.get('cart', {})
 
    if not cart_items:
        flash('Your cart is empty!', 'warning')
        return redirect(url_for('cart'))
 
    # Validate stock before checkout
    for product_id_str, item in cart_items.items():
        product = Product.query.get(int(product_id_str))
        if not product or not product.is_active:
            flash(f'{item["name"]} is no longer available.', 'danger')
            return redirect(url_for('cart'))
        if product.quantity < item['quantity']:
            flash(f'Sorry, only {product.quantity} of {item["name"]} is available.', 'warning')
            return redirect(url_for('cart'))
 
    subtotal = sum(item['price'] * item['quantity'] for item in cart_items.values())
 
    if subtotal < 5000:
        delivery_fee = 500
    elif subtotal < 20000:
        delivery_fee = 1000
    else:
        delivery_fee = 2000
 
    total_amount = subtotal + delivery_fee
 
    if session.get('user_id') and request.method == 'GET':
        user = User.query.get(session['user_id'])
        if user:
            form.customer_name.data = user.username
            form.customer_email.data = user.email
            default_address = Address.query.filter_by(user_id=user.id, is_default=True).first()
            if default_address:
                form.customer_address.data = default_address.address
 
    if form.validate_on_submit():
        try:
            payment_method = form.payment_method.data
 
            command_number = f'CMD-{datetime.now().strftime("%Y%m%d")}-{secrets.token_hex(4).upper()}'
 
            # Order always starts "pending". For mobile money it only
            # becomes "paid" once Fapshi's callback confirms the
            # transaction — never on the strength of user input alone.
            new_command = Command(
                command_number=command_number,
                customer_name=form.customer_name.data,
                customer_email=form.customer_email.data,
                customer_address=form.customer_address.data,
                total_amount=total_amount,
                payment_method=payment_method,
                status='pending'
            )
 
            if session.get('user_id'):
                new_command.user_id = int(session.get('user_id'))
 
            db.session.add(new_command)
            db.session.flush()  # get new_command.id before commit
 
            # Re-check stock and create line items. Stock is NOT
            # decremented here for mobile money — only once payment is
            # confirmed in the callback, so an abandoned Fapshi payment
            # doesn't "ghost reserve" stock forever.
            for product_id_str, item in cart_items.items():
                product_id = int(product_id_str)
                product = Product.query.get(product_id)
 
                if not product or product.quantity < item['quantity']:
                    flash(f'Insufficient stock for {item["name"]}!', 'danger')
                    db.session.rollback()
                    return redirect(url_for('cart'))
 
                db.session.add(CommandItem(
                    command_id=new_command.id,
                    product_id=product_id,
                    quantity=item['quantity'],
                    price_at_time=item['price']
                ))
 
            db.session.commit()
 
            # --- Mobile money: hand off to Fapshi for real verification ---
            if payment_method in ['mtn', 'orange']:
                try:
                    response = fapshi.initiate_pay(
                        amount=int(total_amount),
                        email=new_command.customer_email,
                        redirect_url=url_for('payment_callback', _external=True),
                        external_id=str(new_command.id),
                        message=f'Order {command_number}'
                    )
 
                    new_command.fapshi_trans_id = response['transId']
                    db.session.commit()
 
                    # fallback in case transId isn't echoed back on the
                    # callback URL by Fapshi
                    session['trans_id'] = response['transId']
 
                    return redirect(response['link'])
 
                except Exception as e:
                    new_command.status = 'failed'
                    db.session.commit()
                    flash(f'Payment could not be started: {e}', 'danger')
                    return redirect(url_for('checkout'))
 
            # --- Any other payment method (e.g. cash on delivery) ---
            # No third-party verification exists, so confirm immediately.
            for product_id_str, item in cart_items.items():
                product = Product.query.get(int(product_id_str))
                product.quantity -= item['quantity']
            new_command.status = 'confirmed'
            db.session.commit()
 
            session.pop('cart', None)
            flash(f'Order placed successfully! Your order number is {command_number}', 'success')
            send_order_confirmation_email(new_command)
            return redirect(url_for('command_confirmation', command_id=new_command.id))
 
        except Exception as e:
            db.session.rollback()
            flash(f'An error occurred: {str(e)}', 'danger')
            return render_template(
                'checkout.html', form=form, cart=cart_items,
                subtotal=subtotal, delivery_fee=delivery_fee,
                total_amount=total_amount
            )
 
    # GET (or invalid form)
    return render_template(
        'checkout.html', form=form, cart=cart_items,
        subtotal=subtotal, delivery_fee=delivery_fee,
        total_amount=total_amount
    )
'''
'''
@app.route("/fapshi/checkout/<int:order_id>")
def fapshi_checkout(order_id):
    # Calculate your order total (example: 5000 FCFA)
    total_amount = 5000   # must be at least 100


 # 3. Call initiate_pay to get the payment link
    response = fapshi.initiate_pay(
        amount=total_amount,
        email="customer@example.com",
        redirect_url=url_for("payment_callback", _external=True),
        external_id=str(order_id),
        message=f"Payment for order #{order_id}"
    )

    # 4. Save the transId so we can verify later
    session["trans_id"] = response["transId"]

    # 5. Redirect the customer to Fapshi's payment page
    return redirect(response["link"])
'''
'''
@app.route("/payment/callback")
def payment_callback():
    trans_id = request.args.get("transId") or session.get("trans_id")
 
    if not trans_id:
        flash("No transaction reference found.", "danger")
        return redirect(url_for("my_orders"))
 
    # Ask Fapshi: "Did this transaction succeed?"
    transaction = fapshi.get_payment_status(trans_id)
 
    # Find the matching command (order)
    command = Command.query.filter_by(fapshi_trans_id=trans_id).first()
 
    if not command:
        flash("Order not found.", "danger")
        return redirect(url_for("my_orders"))
 
    if transaction["status"] == "SUCCESSFUL":
        # Idempotency guard: Fapshi may call this more than once.
        # Only decrement stock and email the first time we see "paid".
        if command.status != "paid":
            for item in command.items:  # assumes Command.items relationship
                product = Product.query.get(item.product_id)
                if product:
                    product.quantity -= item.quantity
 
            command.status = "paid"
            db.session.commit()
            send_order_confirmation_email(command)
 
        session.pop('cart', None)
        session.pop('trans_id', None)
        flash("Payment received — thank you!", "success")
        return redirect(url_for("command_confirmation", command_id=command.id))
 
    else:
        command.status = "failed"
        db.session.commit()
        flash(f"Payment {transaction['status'].lower()} — please try again.", "warning")
        return redirect(url_for("checkout"))
 '''

@app.route("/payment/callback")
def payment_callback():
    """Fapshi sends the customer back here after payment."""
    trans_id = request.args.get("transId")

    if not trans_id:
        flash("No transaction reference.", "danger")
        return redirect(url_for("my_orders"))

    # Ask Fapshi for the real status
    try:
        txn = fapshi.get_payment_status(trans_id)
    except Exception as e:
        flash(f"Could not verify payment: {e}", "danger")
        return redirect(url_for("my_orders"))

    # Find the matching order
    order = Command.query.filter_by(fapshi_trans_id=trans_id).first()
    if not order:
        flash("Order not found.", "danger")
        return redirect(url_for("my_orders"))

    if txn["status"] == "SUCCESSFUL":
        order.status = "paid"
        order.paid_at = datetime.utcnow()
        db.session.commit()

        # Clear the cart
        session.pop("cart", None)

        flash("Payment received — thank you!", "success")
        return redirect(url_for("command_confirmation", command_id=order.id))

    else:
        order.status = "failed"
        db.session.commit()

        flash(f"Payment {txn['status'].lower()}. Please try again.", "warning")
        return redirect(url_for("checkout"))
 
def send_order_confirmation_email(command):
    """Send order confirmation email to customer"""
    try:
        msg = Message(
            subject=f"Order Confirmation - {command.command_number}",
            recipients=[command.customer_email],
            html=render_template('emails/order_confirmation.html', command=command)
        )
        mail.send(msg)
    except Exception as e:
        print(f"Failed to send email: {e}")
    
@app.route('/commands')
@admin_required
def commands_list():
    # Admins see all orders
    commands = Command.query.order_by(Command.created_at.desc()).all()
    return render_template('commands.html', commands=commands)

@app.route("/command/<int:command_id>")
def command_confirmation(command_id):
    """Show a single order's details."""
    command = Command.query.get_or_404(command_id)
    return render_template("command_confirmation.html", command=command)

@app.route('/admin/command/<int:command_id>/update_status', methods=['POST'])
@admin_required
def update_command_status(command_id):
    new_status = request.form.get('status')
    allowed = ('pending', 'confirmed', 'shipped', 'delivered', 'cancelled')
    if new_status not in allowed:
        flash('Invalid status selected.', 'warning')
        return redirect(request.referrer or url_for('commands_list'))

    command = Command.query.get_or_404(command_id)
    old_status = command.status
    command.status = new_status
    
    try:
        # If order is cancelled, restore stock
        if new_status == 'cancelled' and old_status != 'cancelled':
            for item in command.items:
                product = Product.query.get(item.product_id)
                if product:
                    product.quantity += item.quantity
        
        db.session.commit()
        
        # Send status update email
        try:
            send_status_update_email(command, old_status, new_status)
        except Exception as e:
            print(f"Email error: {e}")
            
        flash('Order status updated.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Failed to update status: {e}', 'danger')

    return redirect(request.referrer or url_for('commands_list'))

def send_status_update_email(command, old_status, new_status):
    """Send status update email to customer"""
    try:
        msg = Message(
            subject=f"Order {command.command_number} Status Update",
            recipients=[command.customer_email],
            html=render_template('emails/status_update.html', command=command, old_status=old_status, new_status=new_status)
        )
        mail.send(msg)
    except Exception as e:
        print(f"Failed to send email: {e}")

@app.route('/admin/command/<int:command_id>/delete', methods=['POST'])
@admin_required
def delete_command(command_id):
    command = Command.query.get_or_404(command_id)
    try:
        # Only restore stock if not cancelled/delivered
        if command.status not in ['delivered', 'cancelled']:
            for item in command.items:
                product = Product.query.get(item.product_id)
                if product:
                    product.quantity = (product.quantity or 0) + (item.quantity or 0)

        db.session.delete(command)
        db.session.commit()
        flash('Order deleted and stock restored where applicable.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Failed to delete order: {e}', 'danger')

    return redirect(request.referrer or url_for('commands_list'))

@app.route('/admin/command/<int:command_id>/set_transaction', methods=['POST'])
@admin_required
def set_transaction_reference(command_id):
    command = Command.query.get_or_404(command_id)
    tx = request.form.get('transaction_reference', '').strip()
    command.transaction_reference = tx or None
    try:
        db.session.commit()
        flash('Transaction reference saved.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Failed to save transaction reference: {e}', 'danger')
    return redirect(request.referrer or url_for('command_confirmation', command_id=command.id))

@app.route('/admin/command/<int:command_id>/export')
@admin_required
def export_command_csv(command_id):
    command = Command.query.get_or_404(command_id)
    si = io.StringIO()
    writer = csv.writer(si)
    writer.writerow(['Order Number', command.command_number])
    writer.writerow(['Customer Name', command.customer_name])
    writer.writerow(['Customer Email', command.customer_email])
    writer.writerow(['Shipping Address', command.customer_address])
    writer.writerow(['Payment Method', command.payment_method or 'cash'])
    writer.writerow(['Transaction Reference', command.transaction_reference or ''])
    writer.writerow(['Order Date', command.created_at.strftime('%Y-%m-%d %H:%M')])
    writer.writerow(['Status', command.status])
    writer.writerow([])
    writer.writerow(['Product', 'Quantity', 'Price', 'Subtotal'])
    for item in command.items:
        pname = item.product.name if item.product else '[removed]'
        writer.writerow([pname, item.quantity, item.price_at_time, item.quantity * item.price_at_time])
    writer.writerow([])
    writer.writerow(['Total', command.total_amount])

    output = make_response(si.getvalue())
    output.headers['Content-Disposition'] = f"attachment; filename=order_{command.command_number}.csv"
    output.headers['Content-type'] = 'text/csv'
    return output

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        user = User.query.filter_by(email=email).first()
        
        if not user or not user.check_password(password):
            flash('Invalid credentials.', 'danger')
            return redirect(url_for('admin_login'))
        
        if user.role != 'admin':
            flash('This account does not have admin privileges.', 'warning')
            return redirect(url_for('admin_login'))

        session['user_id'] = user.id
        session['username'] = user.username
        session['role'] = 'admin'
        
        # Update last login time
        user.last_login = datetime.now()
        db.session.commit()
        
        flash(f'Welcome back, {user.username}!', 'success')
        return redirect(url_for('admin_dashboard'))

    return render_template('admin_login.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        remember = request.form.get('remember', False)
        
        user = User.query.filter_by(email=email).first()
        if not user or not user.check_password(password):
            flash('Invalid email or password.', 'danger')
            return redirect(url_for('login'))
        
        session['user_id'] = user.id
        session['username'] = user.username
        session['role'] = user.role or 'customer'
        
        if remember:
            session.permanent = True
        
        flash(f'Welcome back, {user.username}!', 'success')
        
        if user.role == 'admin':
            return redirect(url_for('admin_dashboard'))
        return redirect(url_for('index'))
    
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out.', 'info')
    return redirect(url_for('index'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')
        admin_code = request.form.get('admin_code')

        # Validation
        if not username or not email or not password:
            flash('Please fill all required fields.', 'warning')
            return redirect(url_for('register'))
        
        if password != confirm_password:
            flash('Passwords do not match.', 'warning')
            return redirect(url_for('register'))
        
        if len(password) < 8:
            flash('Password must be at least 8 characters long.', 'warning')
            return redirect(url_for('register'))

        if User.query.filter_by(email=email).first():
            flash('Email already registered.', 'warning')
            return redirect(url_for('register'))
        
        if User.query.filter_by(username=username).first():
            flash('Username already taken.', 'warning')
            return redirect(url_for('register'))

        # Create new user
        user = User(username=username, email=email)
        user.set_password(password)
        
        # Check for admin code
        if admin_code and admin_code == app.config.get('ADMIN_CODE'):
            user.role = 'admin'
            flash('Admin account created successfully!', 'success')
        else:
            user.role = 'customer'
            flash('Registration successful! Please log in.', 'success')

        db.session.add(user)
        db.session.commit()
        
        return redirect(url_for('login'))

    return render_template('register.html')

@app.route('/admin/add_product', methods=['GET', 'POST'])
@admin_required
def add_product():
    form = ProductForm()
    if form.validate_on_submit():
        # handle uploaded image
        image_file = request.files.get('image_file')
        image_url = None
        if image_file and image_file.filename:
            # use product name as base filename if possible
            base = secure_filename(form.name.data) if form.name.data else None
            image_url = save_image(image_file, base_name=base)

        product = Product(
            name=form.name.data,
            description=form.description.data,
            price=form.price.data,
            quantity=form.quantity.data,
            image_url=image_url or (form.image_url.data or None)
        )
        db.session.add(product)
        db.session.commit()
        flash('Product added successfully!', 'success')
        return redirect(url_for('admin_products'))
    return render_template('add_product.html', form=form)

@app.route('/product/edit/<int:id>', methods=['GET', 'POST'])
@admin_required
def edit_product(id):
    product = Product.query.get_or_404(id)
    form = ProductForm(obj=product)
    
    if form.validate_on_submit():
        # handle new uploaded image if provided
        image_file = request.files.get('image_file')
        if image_file and image_file.filename:
            base = secure_filename(form.name.data) if form.name.data else f'product_{product.id}'
            image_url = save_image(image_file, base_name=base)
            if image_url:
                product.image_url = image_url

        product.name = form.name.data
        product.description = form.description.data
        product.price = form.price.data
        product.quantity = form.quantity.data
        product.updated_at = datetime.now()
        
        db.session.commit()
        flash(f'{product.name} updated successfully!', 'success')
        return redirect(url_for('admin_products'))
    
    return render_template('edit_product.html', form=form, product=product)

@app.route('/product/delete/<int:id>', methods=['POST'])
@admin_required
def delete_product(id):
    product = Product.query.get_or_404(id)
    product_name = product.name
    
    # Check if this is an AJAX request
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    
    # If product is in any orders, perform a soft-delete (mark inactive)
    if CommandItem.query.filter_by(product_id=id).first():
        product.is_active = False
        product.updated_at = datetime.now()
        try:
            db.session.commit()
            message = f'{product_name} has been deactivated because it is associated with existing orders.'
            if is_ajax:
                return jsonify({'success': True, 'message': message, 'type': 'warning'})
            flash(message, 'warning')
        except Exception as e:
            db.session.rollback()
            error_msg = f'Failed to deactivate product: {str(e)}'
            if is_ajax:
                return jsonify({'success': False, 'message': error_msg}), 500
            flash(error_msg, 'danger')
        if not is_ajax:
            return redirect(url_for('admin_products'))

    # No associated orders: safe to delete completely
    try:
        db.session.delete(product)
        db.session.commit()
        message = f'{product_name} deleted successfully!'
        if is_ajax:
            return jsonify({'success': True, 'message': message, 'type': 'success'})
        flash(message, 'success')
    except Exception as e:
        db.session.rollback()
        error_msg = f'Error deleting product: {str(e)}'
        if is_ajax:
            return jsonify({'success': False, 'message': error_msg}), 500
        flash(error_msg, 'danger')
    
    if not is_ajax:
        return redirect(url_for('admin_products'))

@app.route('/admin/products')
@admin_required
def admin_products():
    # Get filter parameters
    show_inactive = request.args.get('show_inactive', 'false') == 'true'
    
    if show_inactive:
        all_products = Product.query.all()
    else:
        all_products = Product.query.filter_by(is_active=True).all()
    
    return render_template('admin_products.html', products=all_products, show_inactive=show_inactive)

@app.route('/product/toggle/<int:id>', methods=['POST'])
@admin_required
def toggle_product_status(id):
    product = Product.query.get_or_404(id)
    product.is_active = not product.is_active
    product.updated_at = datetime.now()
    
    status = 'activated' if product.is_active else 'deactivated'
    try:
        db.session.commit()
        flash(f'{product.name} has been {status}.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error updating product status: {str(e)}', 'danger')
    
    return redirect(url_for('admin_products'))

@app.route('/account', methods=['GET', 'POST'])
def account():
    if not session.get('user_id'):
        flash('Please log in to access your account.', 'warning')
        return redirect(url_for('login'))

    user = User.query.get(session['user_id'])

    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'update_profile':
            # Update profile information
            user.username = request.form.get('username', user.username)
            user.phone = request.form.get('phone', user.phone)
            db.session.commit()
            session['username'] = user.username
            flash('Profile updated successfully!', 'success')
            
        elif action == 'change_password':
            # Change password
            current = request.form.get('current_password')
            new = request.form.get('new_password')
            confirm = request.form.get('confirm_password')
            
            if not user.check_password(current):
                flash('Current password is incorrect.', 'danger')
            elif new != confirm:
                flash('New passwords do not match.', 'danger')
            elif len(new) < 8:
                flash('Password must be at least 8 characters long.', 'danger')
            else:
                user.set_password(new)
                db.session.commit()
                flash('Password changed successfully!', 'success')
        
        elif action == 'add_address':
            # add address
            label = request.form.get('label')
            address_text = request.form.get('address')
            phone = request.form.get('phone')
            city = request.form.get('city')
            is_default = bool(request.form.get('is_default'))
            
            if not address_text:
                flash('Address cannot be empty.', 'warning')
                return redirect(url_for('account'))

            if is_default:
                # unset others
                Address.query.filter_by(user_id=user.id, is_default=True).update({'is_default': False})

            a = Address(
                user_id=user.id, 
                label=label, 
                address=address_text, 
                phone=phone,
                city=city,
                is_default=is_default
            )
            db.session.add(a)
            db.session.commit()
            flash('Address added.', 'success')

    addresses = Address.query.filter_by(user_id=user.id).order_by(Address.is_default.desc(), Address.created_at.desc()).all()
    recent_orders = Command.query.filter_by(user_id=user.id).order_by(Command.created_at.desc()).limit(5).all()
    
    return render_template('account.html', user=user, addresses=addresses, recent_orders=recent_orders)

@app.route('/account/address/edit/<int:addr_id>', methods=['POST'])
def edit_address(addr_id):
    if not session.get('user_id'):
        flash('Please log in.', 'warning')
        return redirect(url_for('login'))
    
    addr = Address.query.get_or_404(addr_id)
    if addr.user_id != session.get('user_id'):
        flash('Not authorized.', 'danger')
        return redirect(url_for('account'))
    
    addr.label = request.form.get('label', addr.label)
    addr.address = request.form.get('address', addr.address)
    addr.phone = request.form.get('phone', addr.phone)
    addr.city = request.form.get('city', addr.city)
    
    if request.form.get('is_default'):
        # Unset other default addresses
        Address.query.filter_by(user_id=session['user_id'], is_default=True).update({'is_default': False})
        addr.is_default = True
    
    db.session.commit()
    flash('Address updated.', 'success')
    return redirect(url_for('account'))

@app.route('/account/address/delete/<int:addr_id>', methods=['POST'])
def delete_address(addr_id):
    if not session.get('user_id'):
        flash('Please log in.', 'warning')
        return redirect(url_for('login'))
    
    addr = Address.query.get_or_404(addr_id)
    if addr.user_id != session.get('user_id'):
        flash('Not authorized.', 'danger')
        return redirect(url_for('account'))
    
    db.session.delete(addr)
    db.session.commit()
    flash('Address removed.', 'info')
    return redirect(url_for('account'))

@app.route('/wishlist')
def wishlist():
    if not session.get('user_id'):
        flash('Please log in to view your wishlist.', 'warning')
        return redirect(url_for('login'))
    
    items = Wishlist.query.filter_by(user_id=session['user_id']).all()
    return render_template('wishlist.html', items=items)

@app.route('/wishlist/add/<int:product_id>')
def add_to_wishlist(product_id):
    if not session.get('user_id'):
        flash('Please log in to add to wishlist.', 'warning')
        return redirect(url_for('login'))
    
    product = Product.query.get(product_id)
    if not product:
        flash('Product not found.', 'danger')
        return redirect(request.referrer or url_for('products'))
    
    existing = Wishlist.query.filter_by(user_id=session['user_id'], product_id=product_id).first()
    if existing:
        flash('Product already in wishlist.', 'info')
        return redirect(request.referrer or url_for('wishlist'))
    
    w = Wishlist(user_id=session['user_id'], product_id=product_id)
    db.session.add(w)
    db.session.commit()
    flash('Added to wishlist.', 'success')
    return redirect(request.referrer or url_for('wishlist'))

@app.route('/wishlist/remove/<int:product_id>', methods=['POST'])
def remove_from_wishlist(product_id):
    if not session.get('user_id'):
        flash('Please log in.', 'warning')
        return redirect(url_for('login'))
    
    item = Wishlist.query.filter_by(user_id=session['user_id'], product_id=product_id).first()
    if item:
        db.session.delete(item)
        db.session.commit()
        flash('Removed from wishlist.', 'info')
    
    return redirect(request.referrer or url_for('wishlist'))

@app.route('/my-orders')
def my_orders():
    if not session.get('user_id'):
        flash('Please log in to view your orders.', 'warning')
        return redirect(url_for('login'))
    
    user = User.query.get(session['user_id'])
    # Prefer orders linked by user_id, but also include orders placed with the same email (guest checkouts)
    orders = Command.query.filter(
        or_(Command.user_id == user.id, Command.customer_email == user.email)
    ).order_by(Command.created_at.desc()).all()
    
    return render_template('my_orders.html', commands=orders)

@app.route('/shipping-info')
def shipping_info():
    return render_template('shipping_info.html')

@app.route('/privacy-policy')
def privacy_policy():
    return render_template('privacy_policy.html', current_date=datetime.now())

@app.route('/help-center')
def help_center():
    return render_template('help_center.html')

@app.route('/returns-exchanges')
def returns_exchanges():
    return render_template('returns_exchanges.html')

@app.route('/contact', methods=['GET', 'POST'])
def contact():
    form = ContactForm()
    if form.validate_on_submit():
        try:
            # Send email to admin
            msg = Message(
                subject=f"Contact Form: {form.subject.data}",
                recipients=[app.config['MAIL_DEFAULT_SENDER']],
                body=f"""
New message from {form.name.data} ({form.email.data}):

Subject: {form.subject.data}

Message:
{form.message.data}
                """,
                reply_to=form.email.data
            )
            mail.send(msg)
            
            # Send confirmation email to user
            confirmation_msg = Message(
                subject="We received your message",
                recipients=[form.email.data],
                body=f"""
Hello {form.name.data},

Thank you for contacting us! We have received your message and will get back to you as soon as possible.

Your message:
Subject: {form.subject.data}

Best regards,
ShopLinux Support Team
                """
            )
            mail.send(confirmation_msg)
            
            flash('Your message has been sent successfully! We will get back to you soon.', 'success')
            return redirect(url_for('contact'))
        except Exception as e:
            flash(f'An error occurred while sending your message. Please try again later.', 'danger')
    
    return render_template('contact.html', form=form)

# API Routes for AJAX requests
@app.route('/api/cart/count')
def api_cart_count():
    cart = session.get('cart', {})
    count = sum(item['quantity'] for item in cart.values())
    return jsonify({'count': count})

@app.route('/api/product/search')
def api_product_search():
    q = request.args.get('q', '').strip()
    if len(q) < 2:
        return jsonify([])
    
    products = Product.query.filter(
        Product.is_active == True,
        Product.name.ilike(f'%{q}%')
    ).limit(10).all()
    
    results = [{'id': p.id, 'name': p.name, 'price': p.price, 'image': p.image_url} for p in products]
    return jsonify(results)

@app.route('/api/check-stock/<int:product_id>')
def api_check_stock(product_id):
    product = Product.query.get_or_404(product_id)
    return jsonify({
        'id': product.id,
        'in_stock': product.quantity > 0,
        'quantity': product.quantity
    })

# Create database tables
with app.app_context():
    db.create_all()
    
    # Check if admin user exists, create if not
    admin_email = os.environ.get('ADMIN_EMAIL', 'admin@example.com')
    admin_password = os.environ.get('ADMIN_PASSWORD', 'Admin@123')  # Default password, change in production!
    
    admin_user = User.query.filter_by(role='admin').first()
    if not admin_user:
        # Create admin user
        u = User(
            username='admin',
            email=admin_email,
            role='admin',
            created_at=datetime.now()
        )
        u.set_password(admin_password)
        db.session.add(u)
        db.session.commit()
        print(f'Admin user created with email: {admin_email}')
        print(f'Default password: {admin_password} (CHANGE THIS IN PRODUCTION!)')
    else:
        print(f'Admin user exists: {admin_user.email}')
        
        # Optionally update admin password if environment variable is set
        if os.environ.get('UPDATE_ADMIN_PASSWORD', 'false').lower() == 'true':
            new_password = os.environ.get('NEW_ADMIN_PASSWORD')
            if new_password:
                admin_user.set_password(new_password)
                db.session.commit()
                print(f'Admin password updated for {admin_user.email}')

    # Create demo user if not exists
    demo_email = os.environ.get('DEMO_EMAIL', 'user@example.com')
    demo_password = os.environ.get('DEMO_PASSWORD', 'User@123')
    
    if not User.query.filter_by(email=demo_email).first():
        u = User(
            username='demo',
            email=demo_email,
            role='customer',
            created_at=datetime.now()
        )
        u.set_password(demo_password)
        db.session.add(u)
        db.session.commit()
        print(f'Demo user created: {demo_email}')
        print(f'Demo password: {demo_password}')

    # Safe migration: add is_active column if missing
    try:
        with db.engine.connect() as conn:
            # Check if column exists (SQLite specific)
            result = conn.execute(text("PRAGMA table_info('products')"))
            cols = [row[1] for row in result]
            if 'is_active' not in cols:
                conn.execute(text("ALTER TABLE products ADD COLUMN is_active INTEGER DEFAULT 1"))
                conn.commit()
                print('Added is_active column to products table')
    except Exception as e:
        print(f'Migration note: {e}')

    # Safe migration: add user_id to commands if missing
    try:
        with db.engine.connect() as conn:
            result = conn.execute(text("PRAGMA table_info('commands')"))
            cols = [row[1] for row in result]
            if 'user_id' not in cols:
                conn.execute(text("ALTER TABLE commands ADD COLUMN user_id INTEGER"))
                conn.commit()
                print('Added user_id column to commands table')
    except Exception as e:
        print(f'Migration note: {e}')

    # Safe migration: add payment_method to commands if missing
    try:
        with db.engine.connect() as conn:
            result = conn.execute(text("PRAGMA table_info('commands')"))
            cols = [row[1] for row in result]
            if 'payment_method' not in cols:
                # default to 'cash'
                conn.execute(text("ALTER TABLE commands ADD COLUMN payment_method TEXT DEFAULT 'cash'"))
                conn.commit()
                print('Added payment_method column to commands table')
    except Exception as e:
        print(f'Migration note: {e}')

    # Safe migration: add transaction_reference to commands if missing
    try:
        with db.engine.connect() as conn:
            result = conn.execute(text("PRAGMA table_info('commands')"))
            cols = [row[1] for row in result]
            if 'transaction_reference' not in cols:
                conn.execute(text("ALTER TABLE commands ADD COLUMN transaction_reference TEXT"))
                conn.commit()
                print('Added transaction_reference column to commands table')
    except Exception as e:
        print(f'Migration note: {e}')

    # Safe migration: add phone and city to addresses if missing
    try:
        with db.engine.connect() as conn:
            result = conn.execute(text("PRAGMA table_info('addresses')"))
            cols = [row[1] for row in result]
            if 'phone' not in cols:
                conn.execute(text("ALTER TABLE addresses ADD COLUMN phone TEXT"))
                conn.commit()
                print('Added phone column to addresses table')
            if 'city' not in cols:
                conn.execute(text("ALTER TABLE addresses ADD COLUMN city TEXT"))
                conn.commit()
                print('Added city column to addresses table')
    except Exception as e:
        print(f'Migration note: {e}')

    # Safe migration: add last_login and phone to users if missing
    try:
        with db.engine.connect() as conn:
            result = conn.execute(text("PRAGMA table_info('users')"))
            cols = [row[1] for row in result]
            if 'last_login' not in cols:
                conn.execute(text("ALTER TABLE users ADD COLUMN last_login TIMESTAMP"))
                conn.commit()
                print('Added last_login column to users table')
            if 'phone' not in cols:
                conn.execute(text("ALTER TABLE users ADD COLUMN phone TEXT"))
                conn.commit()
                print('Added phone column to users table')
    except Exception as e:
        print(f'Migration note: {e}')

if __name__ == '__main__': app.run(host='0.0.0.0', 
    port=int(os.environ.get('PORT', 5000)), 
    debug=os.environ.get('FLASK_DEBUG', 'False') == 'True')
