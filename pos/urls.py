# pos/urls.py

from django.urls import path
from . import views

app_name = 'pos'

urlpatterns = [
    # Main POS View
    path('', views.pos_view, name='pos_view'),
    
    # AJAX Endpoints (Updated names to match pos.html)
    path('ajax/get-products/', views.get_products_for_pos, name='get_products_for_pos'),
    path('ajax/search-customers/', views.get_customers_for_pos, name='get_customers_for_pos'),
    path('ajax/create-customer/', views.pos_create_customer, name='pos_create_customer'),

    # Session Management
    path('sessions/', views.pos_session_list, name='pos_session_list'), 
    path('session/<int:pk>/close/', views.pos_session_close, name='pos_session_close'),
    path('session/<int:pk>/report/', views.pos_session_report, name='pos_session_report'),
    
    # Receipt
    path('receipt/<int:order_id>/', views.pos_receipt_view, name='pos_receipt_view'),

    # Deprecated/Placeholder URLs (Keep them if needed to avoid errors)
    path('ajax/add-to-cart/', views.pos_add_to_cart, name='pos_add_to_cart'),
    path('ajax/remove-from-cart/', views.pos_remove_from_cart, name='pos_remove_from_cart'),
    path('ajax/get-cart/', views.pos_get_cart, name='pos_get_cart'),
    path('ajax/checkout/', views.pos_checkout_view, name='pos_checkout_view'),
]