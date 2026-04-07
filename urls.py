# finance/urls.py
from django.urls import path, include
from . import views

app_name = 'finance'

urlpatterns = [
    path('', views.finance_dashboard, name='dashboard'),

    path('gl/', include('finance.gl.urls', namespace='gl')),
    path('ap/', include('finance.ap.urls', namespace='ap')),
    path('ar/', include('finance.ar.urls', namespace='ar')),
    path('banking/', include('finance.banking.urls', namespace='banking')),
    path('assets/', include('finance.assets.urls', namespace='assets')),
    path('cash/', include('finance.cash.urls', namespace='cash')),
    path('investments/', include('finance.investments.urls', namespace='investments')),
]