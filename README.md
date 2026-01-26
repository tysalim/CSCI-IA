PriceTrax – AI/CS IA Project

A personal project built for the CSCI Internal Assessment

🧾 Overview

PriceTrax is a web-based application built using Python (Flask), SQLite (via SQLAlchemy ORM), and a simple scraper, which allows users to track product prices across e-commerce platforms, monitor changes, and receive notifications when price drops or stock changes occur. It was developed as part of the Computer Science Internal Assessment (IA) project.

🔍 Features

User registration & login with protected password hashing.

A database of products with price history, last-checked timestamps, and stock status.

Watchlist functionality: users can add products to their watchlist and receive alerts when price drops or low stock occur.

A web interface (Flask + HTML/CSS templates) to view products, watchlists, and price histories.

A scraper module (scraper.py) to fetch updated product data for tracking.

Simple, lightweight architecture using SQLite (price_trax.db) for rapid setup & testing.

🏗️ Architecture & Files
File	Description
app.py	Main Flask application, handles routing, user sessions, watchlist addition/removal, and interaction with the database.
models.py	SQLAlchemy model definitions: User, Product, PriceHistory, Watchlist. Defines relationships and schema.
scraper.py	Module to fetch product data (price, availability) from target platforms and update the database accordingly.
requirements.txt	Python dependencies needed to run the project (Flask, SQLAlchemy, etc.).
templates/	Folder containing HTML templates for the web interface.
styles.css	Basic CSS for styling the web pages.
price_trax.db	SQLite database file (used for development/testing).
__pycache__/	Python cache folder (auto-generated; can be ignored).
🚀 Getting Started
Prerequisites

Python 3.x installed on your machine

pip (Python package installer)

(Optional) A virtual environment for clean dependencies

Installation

Clone the repository:

git clone https://github.com/tysalim/CSCI-IA.git
cd CSCI-IA


(Optional) Create and activate a virtual environment:

python3 -m venv venv
source venv/bin/activate       # Linux/macOS  
venv\Scripts\activate          # Windows  


Install dependencies:

pip install -r requirements.txt


Initialize the database (if not already present):

You can run Python and create tables:

from models import Base
from sqlalchemy import create_engine
engine = create_engine('sqlite:///price_trax.db')
Base.metadata.create_all(engine)


Alternatively, if price_trax.db is already provided you may skip this step.

Running the App
python app.py


Then open your browser and navigate to http://127.0.0.1:5000/ (or whatever Flask outputs) to view the UI.

Using the Scraper

You can run scraper.py manually (or automate via cron/scheduler) to update product price and stock information. The scraper will update Product entries and add new PriceHistory rows accordingly.

📂 Database & Model Relationships

Here are the main relationships:

A User can have many Watchlist items.

A Product can have many Watchlist items (i.e., many users can watch the same product).

A Product has many PriceHistory entries (tracking past price changes).

The Watchlist table records the user_id and product_id, and stores metadata: whether the user wants price-drop notifications, low-stock notifications, and what their last notified price was.

This structure allows efficient queries like:

“Which users should be notified about this product’s new price?”

“What’s the price history of a given product?”

“Which products are on this user’s watchlist?”

✅ Next Steps & Enhancements

Some possible future improvements:

Implement user authentication with email verification / password reset.

Add real-time notifications (email or SMS) when thresholds are triggered.

Improve the scraping logic: support more e-commerce platforms, handle anti-bot protections, scheduling.

Add filtering, sorting, and statistics in the UI (e.g., graphing price history).

Move from SQLite to a production-grade database (PostgreSQL/MySQL) for scalability.

Deploy the app to a cloud provider (Heroku, AWS, etc.) and enable live usage.

📝 License & Attribution

This project is developed by [Your Name / Your GitHub Handle].
Feel free to use, modify, and distribute as you see fit (add your preferred license here).

📞 Feedback & Contact

If you encounter issues, have suggestions, or want to contribute, you can open an issue or submit a pull request in this repository.