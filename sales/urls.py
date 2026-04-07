# sales/urls.py

from django.urls import path
from . import views

app_name = 'sales'

urlpatterns = [
    # Pages
    path('', views.sales_order_list, name='sales_order_list'),
    path('create/', views.create_sales_order, name='create_sales_order'),
    path('<int:pk>/', views.sales_order_detail, name='sales_order_detail'),
    path('<int:pk>/edit/', views.edit_sales_order, name='edit_sales_order'),
    path('<int:pk>/delete/', views.delete_sales_order, name='delete_sales_order'),
    
    # --- New Flow Actions ---
    path('<int:pk>/confirm/', views.confirm_sales_order, name='confirm_sales_order'),
    path('<int:pk>/add-payment/', views.add_payment_to_order, name='add_payment_to_order'),
    path('<int:pk>/fulfill/', views.fulfill_sales_order, name='fulfill_sales_order'),
    path('sales-order/<int:pk>/update-status/', views.update_sales_order_status, name='update_sales_order_status'),
    
    # Export & Returns
    path('export/pdf/<int:pk>/', views.export_sales_order_pdf, name='export_sales_order_pdf'),
    path('returns/', views.create_sales_return, name='create_sales_return'),
    path('returns/<int:pk>/', views.sales_return_detail, name='sales_return_detail'),

    # AJAX URLs
    path('ajax/get-product-price/', views.get_product_sale_price_ajax, name='get_product_sale_price'),
    path('get-lots/', views.get_lots_by_location_and_product, name='get_lots_by_location_and_product'),
    path('ajax/validate-coupon/', views.validate_coupon, name='validate_coupon'),
    path('search-products/', views.search_products_for_sale, name='search_products_for_sale'),
]