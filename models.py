from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()

class Product(db.Model):
    """Products table"""
    __tablename__ = 'products'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=True)
    price = db.Column(db.Float, nullable=False)
    quantity = db.Column(db.Integer, default=0)
    image_url = db.Column(db.String(200), nullable=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
   # is_active = db.Column(db.Boolean, default=True, nullable=False) 
    # Relationship with CommandItem (add cascade delete)
    command_items = db.relationship('CommandItem', backref='product', lazy=True, cascade='all, delete-orphan')
    #is_active = db.Column(db.Boolean, default=True, nullable=False) 

    def __repr__(self):
        return f'<Product {self.name}>'

class Command(db.Model):
    """Commands table (orders)"""
    __tablename__ = 'commands'
    
    id = db.Column(db.Integer, primary_key=True)
    command_number = db.Column(db.String(50), unique=True, nullable=False)
    customer_name = db.Column(db.String(100), nullable=False)
    customer_email = db.Column(db.String(100), nullable=False)
    customer_address = db.Column(db.Text, nullable=False)
    total_amount = db.Column(db.Float, default=0.0)
    status = db.Column(db.String(20), default='pending')  # pending, confirmed, shipped, delivered
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    # Optional link to a registered user who placed the order
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    user = db.relationship('User', backref=db.backref('commands', lazy=True))
    # Payment method selected at checkout: 'mtn', 'orange', 'cash'
    payment_method = db.Column(db.String(30), default='cash', nullable=True)
    # Optional transaction reference for mobile money payments (admin can record)
    transaction_reference = db.Column(db.String(120), nullable=True)
    fapshi_trans_id = db.Column(db.String(120), nullable=True, unique=True)
    
    # Relationship with CommandItem (add cascade delete)
    items = db.relationship('CommandItem', backref='command', lazy=True, cascade='all, delete-orphan')
    
    def __repr__(self):
        return f'<Command {self.command_number}>'

class CommandItem(db.Model):
    """Command items table (linking products to commands)"""
    __tablename__ = 'command_items'
    
    id = db.Column(db.Integer, primary_key=True)
    command_id = db.Column(db.Integer, db.ForeignKey('commands.id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    price_at_time = db.Column(db.Float, nullable=False)  # price when ordered
    
    def __repr__(self):
        return f'<CommandItem {self.id}>'


class User(db.Model):
    """Users table for customers and admins"""
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
    role = db.Column(db.String(20), default='customer')  # 'customer' or 'admin'
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def set_password(self, password: str):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

    def is_admin(self) -> bool:
        return self.role == 'admin'

    def __repr__(self):
        return f'<User {self.email} ({self.role})>'


class Address(db.Model):
    __tablename__ = 'addresses'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    label = db.Column(db.String(60), nullable=True)
    address = db.Column(db.Text, nullable=False)
    phone = db.Column(db.String(30), nullable=True)
    is_default = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<Address {self.label} for {self.user_id}>'


class Wishlist(db.Model):
    __tablename__ = 'wishlists'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    product = db.relationship('Product')

    def __repr__(self):
        return f'<Wishlist user={self.user_id} product={self.product_id}>'
