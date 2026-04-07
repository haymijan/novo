from django.contrib import admin
from django.urls import path, include
from django.contrib.auth import views as auth_views
from django.conf import settings
from django.conf.urls.static import static
from .views import dashboard, CustomPasswordResetView

urlpatterns = [
    path('admin/', admin.site.urls),
    
    path('accounts/', include('accounts.urls')),

    path('', dashboard, name='dashboard'), 
    path('login/', auth_views.LoginView.as_view(template_name='registration/login.html'), name='login'),
    path('logout/', auth_views.LogoutView.as_view(template_name='logout.html'), name='logout'),

    path("password_reset/", CustomPasswordResetView.as_view(), name="password_reset"),
    path('password_reset/done/', auth_views.PasswordResetDoneView.as_view(template_name='registration/password_reset_done.html'), name='password_reset_done'),
    path('reset/<uidb64>/<token>/', auth_views.PasswordResetConfirmView.as_view(template_name='registration/password_reset_confirm.html'), name='password_reset_confirm'),
    path('reset/done/', auth_views.PasswordResetCompleteView.as_view(template_name='registration/password_reset_complete.html'), name='password_reset_complete'),

    path('products/', include('products.urls', namespace='products')),
    path('partners/', include('partners.urls', namespace='partners')),
    path('sales/', include('sales.urls', namespace='sales')),
    path('purchases/', include('purchase.urls', namespace='purchase')),
    path('stock/', include('stock.urls', namespace='stock')),
    path('reports/', include('reports.urls', namespace='reports')),
    path('pos/', include('pos.urls', namespace='pos')),
    path('management/', include(('management.urls', 'management'), namespace='management')),
    path('costing/', include('costing.urls', namespace='costing')),
    path('finance/', include('finance.urls', namespace='finance')),
    path('marketing/', include('marketing.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)