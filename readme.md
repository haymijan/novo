# Inventory Management System (A.I. Powered)

This is a comprehensive and intelligent Inventory Management System developed using Python and the Django web framework. The system aims to provide robust features for managing product stock, sales, purchases, and customer/supplier relationships, with a vision to incorporate advanced AI capabilities for predictive analysis and optimized inventory control, similar to powerful ERP solutions like Odoo.

## Features

# Inventory Management System (A.I. Powered)

This is a comprehensive and intelligent Inventory Management System developed using Python and the Django web framework. The system has been refactored into a modular, multi-app architecture to ensure scalability and maintainability, similar to powerful ERP solutions like Odoo.

## Features

The system is organized into several distinct applications, each responsible for a specific business domain:

### Products App (`products`)
* Add, edit, and view product details, including images and barcodes.
* Manage product categories.
* Handle various Units of Measure (UoM) like Pcs, Kg, Box, etc., and their categories.

### Partners App (`partners`)
* Maintain a comprehensive list of customers and suppliers.
* Add, edit, and view partner details (contact info, address, etc.).
* AJAX-powered modals to add new partners directly from order forms.

### Purchase App (`purchase`)
* Create, track, and manage purchase orders.
* Record incoming stock against specific purchase orders.
* Manage supplier pricelists for products through a dedicated `ProductSupplier` model.
* Export purchase order lists and individual orders to PDF/Excel.

### Sales App (`sales`)
* Create, track, and manage sales orders.
* Calculate total order amounts automatically.
* Fulfill orders, which updates stock levels accordingly.
* Generate printable receipts for sales.

### Stock App (`stock`)
* Manage multiple warehouses and specific product locations within them.
* Track real-time inventory levels for each product at each location.
* Handle Lot/Serial number tracking for products.
* Record all inventory movements (receipts, sales, transfers, adjustments) in a transaction ledger.
* Perform inventory adjustments to correct stock levels.
* Generate detailed stock movement reports.

### POS App (`pos`) - Point of Sale
* A streamlined, fast interface for quick sales transactions.
* Real-time product search and cart management.
* Barcode scanning functionality using QuaggaJS.
* Integrated payment processing (Cash/Card) and receipt printing.

### Reports App (`reports`)
* Generate daily sales reports with filtering by date, user, and branch/warehouse.
* (Future) Advanced analytical reports on sales, stock, and purchasing trends.

## Technologies Used

* **Backend:** Python 3.x, Django Web Framework
* **Database:** SQLite3 (default, can be easily migrated to PostgreSQL/MySQL for production)
* **Frontend:** HTML5, CSS3 (`static/css/style.css`), JavaScript (including jQuery and Chart.js)
* **Barcode Generation:** `python-barcode`
* **PDF/Excel Reporting:** `reportlab`, `openpyxl`
* **Development Environment:** Virtual Environment (`venv/`)

## AI Integration (Future/Planned)

The project incorporates Artificial Intelligence, primarily for:
* **Sales Forecasting:** Analyzing historical sales data to predict future demand and optimize stock levels.
* **Inventory Optimization:** Suggesting optimal reorder points and quantities to minimize carrying costs and avoid stockouts.
* **Automated Alerts:** Providing smart alerts for low stock, potential expiry (if lot tracking involves expiry dates), and unusual inventory movements.

## Project Structure

The project follows a standard Django application structure:

inventory_project/
├── inventory_system/
│   ├── __init__.py
│   ├── asgi.py
│   ├── settings.py
│   ├── urls.py
│   ├── views.py
│   ├── wsgi.py
│   ├── templatetags/
│   │   ├── __init__.py
│   │   └── inventory_filters.py
│   └── templates/
│       ├── base.html
│       ├── home.html
│       ├── login.html
│       ├── 404.html
│       ├── confirm_delete.html
│       ├── dashboard.html
│       ├── test.html
│       ├── admin/
│       │   └── index.html
│       └── includes/
│           └── pagination.html
│
├── accounts/
│   ├── migrations/
│   ├── __init__.py
│   ├── admin.py
│   ├── apps.py
│   ├── models.py
│   ├── tests.py
│   └── views.py
│
├── management/
│   ├── migrations/
│   ├── __init__.py
│   ├── admin.py
│   ├── apps.py
│   ├── models.py
│   ├── tests.py
│   ├── urls.py
│   ├── views.py
│   ├── management/
│   │    └── commands/
│   │       ├── __init__.py
│   │       ├── backup.py
│   │       ├── find_mpo_files.py
│   │       ├── reconcile_lots.py
│   │       └── reconcile_stock.py
│   └── templates/
│       └── management/
│           └── backup_restore.html
│
├── partners/
│   ├── migrations/
│   ├── __init__.py
│   ├── admin.py
│   ├── apps.py
│   ├── forms.py
│   ├── models.py
│   ├── tests.py
│   ├── urls.py
│   ├── views.py
│   └── templates/
│       └── partners/
│           ├── add_customer.html
│           ├── add_supplier.html
│           ├── customer_list.html
│           ├── edit_customer.html
│           ├── edit_supplier.html
│           └── supplier_list.html
│
├── pos/
│   ├── migrations/
│   ├── __init__.py
│   ├── admin.py
│   ├── apps.py
│   ├── models.py
│   ├── tests.py
│   ├── urls.py
│   ├── views.py
│   └── templates/
│       └── pos/
│           ├── pos.html
│           └── pos_receipt.html
│
├── products/
│   ├── migrations/
│   ├── __init__.py
│   ├── admin.py
│   ├── apps.py
│   ├── forms.py
│   ├── models.py
│   ├── tests.py
│   ├── urls.py
│   ├── views.py
│   └── templates/
│       └── products/
│           ├── add_brand.html
│           ├── add_category.html
│           ├── add_product.html
│           ├── add_uom_category.html
│           ├── add_unit_of_measure.html
│           ├── brand_list.html
│           ├── category_list.html
│           ├── edit_brand.html
│           ├── edit_category.html
│           ├── edit_product.html
│           ├── edit_uom_category.html
│           ├── edit_unit_of_measure.html
│           ├── product_list.html
│           ├── product_stock_by_location.html
│           ├── uom_category_list.html
│           └── unit_of_measure_list.html
│
├── purchase/
│   ├── migrations/
│   ├── __init__.py
│   ├── admin.py
│   ├── apps.py
│   ├── forms.py
│   ├── models.py
│   ├── tests.py
│   ├── urls.py
│   ├── views.py
│   ├── templatetags/
│   │   ├── __init__.py
│   │   └── purchase_filters.py
│   └── templates/
│       └── purchase/
│           ├── create_purchase_order.html
│           ├── create_stock_transfer_request.html
│           ├── edit_purchase_order.html
│           ├── purchase_order_detail.html
│           ├── purchase_order_list.html
│           ├── receive_purchase_order.html
│           ├── stock_transfer_detail.html
│           └── stock_transfer_request_list.html
│
├── reports/
│   ├── migrations/
│   ├── __init__.py
│   ├── admin.py
│   ├── apps.py
│   ├── forms.py
│   ├── models.py
│   ├── tests.py
│   ├── urls.py
│   ├── views.py
│   └── templates/
│       └── reports/
│           └── daily_sales_report.html
│
├── costing/
│   ├── migrations/
│   ├── __init__.py
│   ├── admin.py
│   ├── apps.py
│   ├── forms.py
│   ├── models.py
│   ├── tests.py
│   ├── urls.py
│   ├── views.py
│   └── templates/
│       └── costing/
│           └── job_costing_report.html
│
├── sales/
│   ├── migrations/
│   ├── __init__.py
│   ├── admin.py
│   ├── apps.py
│   ├── forms.py
│   ├── models.py
│   ├── tests.py
│   ├── urls.py
│   ├── views.py
│   └── templates/
│       └── sales/
│           ├── create_sales_order.html
│           ├── edit_sales_order.html
│           ├── fulfill_sales_order.html
│           ├── receipt.html
│           ├── sales_order_detail.html
│           └── sales_order_list.html
│
├── stock/
│   ├── migrations/
│   ├── __init__.py
│   ├── admin.py
│   ├── apps.py
│   ├── forms.py
│   ├── models.py
│   ├── services.py
│   ├── signals.py (Empty file)
│   ├── tests.py
│   ├── urls.py
│   ├── views.py
│   └── templates/
│       └── stock/
│           ├── add_location.html
│           ├── add_lot_serial.html
│           ├── add_warehouse.html
│           ├── edit_location.html
│           ├── edit_lot_serial.html
│           ├── edit_transaction.html
│           ├── edit_warehouse.html
│           ├── inventory_adjustment.html
│           ├── location_list.html
│           ├── lot_serial_list.html
│           ├── product_stock_details
│           ├── record_transaction.html
│           ├── stock_movement_report.html
│           ├── transaction_list.html
│           └── warehouse_list.html
│
├── static/
│   ├── css/
│   │    └── style.css
│   └── images/
│
├── media/
│   ├── barcodes/
│   └── product_images/
│
├── backups/
│   └── (এখানে ব্যাকআপ ফাইলগুলো সেভ হবে)
│
├── venv/
│   └── (ভার্চুয়াল এনভায়রনমেন্টের ফাইল)
│
├── db.sqlite3
├── manage.py
├── readme.md
├── requirements.txt
└── run_backup.bat


inventory_project/
│
├── inventory_system/         # মূল প্রজেক্ট কনফিগারেশন ফোল্ডার
│   ├── settings.py           # প্রজেক্টের সকল সেটিংস
│   ├── urls.py               # প্রজেক্টের প্রধান URL কনফিগারেশন
│   ├── wsgi.py               # প্রোডাকশন সার্ভারের জন্য WSGI কনফিগারেশন
│   ├── asgi.py               # ASGI কনফিগারেশন
│   └── templates/            # প্রোজেক্ট-ব্যাপী টেমপ্লেট (base.html, login.html ইত্যাদি)
│
├── accounts/                 # ব্যবহারকারী ব্যবস্থাপনা অ্যাপ
│   ├── models.py             # কাস্টম ইউজার মডেল (CustomUser)
│   ├── admin.py              # অ্যাডমিন সাইটে ইউজার মডেল রেজিস্ট্রেশন
│   └── ...
│
├── products/                 # প্রোডাক্ট-সংক্রান্ত অ্যাপ
│   ├── models.py             # Product, Category, Brand ইত্যাদি মডেল
│   ├── views.py              # প্রোডাক্ট লিস্ট, অ্যাড, এডিট করার লজিক
│   ├── forms.py              # প্রোডাক্ট-সম্পর্কিত ফর্ম
│   ├── urls.py               # প্রোডাক্ট অ্যাপের URL সমূহ
│   └── templates/products/   # প্রোডাক্ট-সম্পর্কিত HTML টেমপ্লেট
│
├── stock/                    # ইনভেনটরি ও স্টক ব্যবস্থাপনা অ্যাপ
│   ├── models.py             # Warehouse, Location, Stock, InventoryTransaction মডেল
│   ├── services.py           # (নতুন তৈরি করা) কেন্দ্রীয় স্টক ব্যবস্থাপনার সার্ভিস
│   ├── views.py              # স্টক অ্যাডজাস্টমেন্ট, লোকেশন ও ওয়্যারহাউজ ব্যবস্থাপনার লজিক
│   ├── management/commands/  # কাস্টম ম্যানেজমেন্ট কমান্ড (reconcile_stock)
│   └── ...
│
├── sales/                    # সেলস-সংক্রান্ত অ্যাপ
│   ├── models.py             # SalesOrder, SalesOrderItem মডেল
│   ├── views.py              # সেলস অর্ডার তৈরি, ফুলফিল করার লজিক
│   └── ...
│
├── purchase/                 # পারচেজ-সংক্রান্ত অ্যাপ
│   ├── models.py             # PurchaseOrder, StockTransferRequest ইত্যাদি মডেল
│   ├── views.py              # পারচেজ অর্ডার তৈরি, রিসিভ করার লজিক
│   └── ...
│
├── pos/                      # POS (Point of Sale) অ্যাপ
│   ├── views.py              # POS ইন্টারফেস এবং সেলস প্রক্রিয়াকরণের লজিক
│   ├── templates/pos/        # POS ইন্টারফেসের HTML টেমপ্লেট
│   └── ...
│
├── partners/                 # কাস্টমার ও সাপ্লায়ার ব্যবস্থাপনার অ্যাপ
│   ├── models.py             # Customer, Supplier মডেল
│   └── ...
│
├── reports/                  # রিপোর্ট জেনারেট করার অ্যাপ
│   ├── views.py              # বিভিন্ন রিপোর্ট (যেমন: ডেইলি সেলস) তৈরির লজিক
│   └── ...
│
├── costing/                  # কস্টিং-সম্পর্কিত অ্যাপ
│   ├── models.py             # JobCost মডেল
│   └── ...
│
├── management/               # ব্যাকআপ ও অন্যান্য ব্যবস্থাপনার অ্যাপ
│   ├── management/commands/  # কাস্টম ম্যানেজমেন্ট কমান্ড (backup)
│   └── ...
│
├── static/                   # CSS, JavaScript, এবং ইমেজ ফাইল
│   └── css/style.css        
│
├── media/                    # ব্যবহারকারীদের আপলোড করা ফাইল (যেমন: প্রোডাক্টের ছবি)
│   └── product_images/
│
├── manage.py                 # Django প্রজেক্ট управления (management) স্ক্রিপ্ট
└── requirements.txt          # প্রজেক্টের লাইব্রেরি নির্ভরতা তালিকা