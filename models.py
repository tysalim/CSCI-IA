from datetime import datetime
import json
from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean, ForeignKey, UniqueConstraint, Text
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class User(Base):
    __tablename__ = 'users'

    id = Column(Integer, primary_key=True)
    email = Column(String(255), unique=True, nullable=False)
    username = Column(String(100), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    matrix = Column(Text, nullable=True, default='[]')
    created_at = Column(DateTime, default=datetime.now)

    watchlist_items = relationship('Watchlist', back_populates='user', cascade='all, delete-orphan')

    def get_matrix(self):
        """Return the stored matrix as a Python list of lists."""
        if not self.matrix:
            return []
        try:
            return json.loads(self.matrix)
        except Exception:
            return []

    def set_matrix(self, matrix_obj):
        """Set the stored matrix given a Python list-of-lists and serialize to JSON."""
        try:
            self.matrix = json.dumps(matrix_obj)
        except Exception:
            # fallback to empty list
            self.matrix = '[]'


class Product(Base):
    __tablename__ = 'products'
    __table_args__ = (
        UniqueConstraint('platform', 'platform_product_id', name='uq_platform_product'),
    )

    id = Column(Integer, primary_key=True)
    platform = Column(String(50), nullable=False)
    platform_product_id = Column(String(255), nullable=False)
    name = Column(String(500), nullable=False)
    seller = Column(String(255))
    last_price = Column(Float)
    currency = Column(String(10))
    url = Column(String(1000), nullable=False)
    in_stock = Column(Boolean, default=True)
    last_checked_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.now)

    price_history = relationship('PriceHistory', back_populates='product', cascade='all, delete-orphan', order_by='PriceHistory.created_at.desc()')
    watchers = relationship('Watchlist', back_populates='product', cascade='all, delete-orphan')


class PriceHistory(Base):
    __tablename__ = 'price_history'

    id = Column(Integer, primary_key=True)
    product_id = Column(Integer, ForeignKey('products.id'), nullable=False)
    price = Column(Float, nullable=False)
    currency = Column(String(10))
    created_at = Column(DateTime, default=datetime.now)

    product = relationship('Product', back_populates='price_history')


class Watchlist(Base):
    __tablename__ = 'watchlist'
    __table_args__ = (
        UniqueConstraint('user_id', 'product_id', name='uq_user_product'),
    )

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    product_id = Column(Integer, ForeignKey('products.id'), nullable=False)
    seller = Column(String(255))
    notify_price_drop = Column(Boolean, default=True)
    last_notified_price = Column(Float)
    created_at = Column(DateTime, default=datetime.now)

    user = relationship('User', back_populates='watchlist_items')
    product = relationship('Product', back_populates='watchers')


class VisitHistory(Base):
    __tablename__ = 'visit_history'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    name = Column(String(500), nullable=False)
    url = Column(String(1000), nullable=False)
    price = Column(Float)
    currency = Column(String(10))
    created_at = Column(DateTime, default=datetime.now)

    user = relationship('User', backref='visit_history')