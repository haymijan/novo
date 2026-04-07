from django.urls import path
from . import views

app_name = 'marketing'

urlpatterns = [
    # Coupon Management
    path('coupons/', views.coupon_list, name='coupon_list'),
    path('coupons/create/', views.create_coupon, name='create_coupon'),
    
    # Gift Card Management
    path('gift-cards/', views.gift_card_list, name='gift_card_list'),
    path('gift-cards/create/', views.create_gift_card, name='create_gift_card'), # Single Issue
    
    # [NEW] Batch Generate URL
    path('gift-cards/batch-generate/', views.generate_batch_cards, name='generate_batch_cards'),

    path('gift-card/print/<int:pk>/', views.print_gift_card, name='print_gift_card'),
    path('gift-card/email/<int:pk>/', views.email_gift_card, name='email_gift_card'),

    # AJAX & Details
    path('ajax/check-gift-card/', views.check_gift_card_balance, name='check_gift_card'),
    path('gift-card/view/<int:pk>/', views.gift_card_detail, name='gift_card_detail'),
]