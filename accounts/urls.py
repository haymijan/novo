from django.urls import path
from . import views
from django.contrib.auth import views as auth_views

urlpatterns = [
    path('login/', auth_views.LoginView.as_view(template_name='registration/login.html'), name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
    path('login-phone/', views.login_with_phone, name='login_phone'),
    path('verify-otp/', views.verify_otp, name='verify_otp'),
]