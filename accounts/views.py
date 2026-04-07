from django.shortcuts import render, redirect
from django.contrib.auth import login
from django.contrib import messages
from django.core.cache import cache
import random
from .models import User
from .forms import PhoneLoginForm, OTPVerificationForm
from .utils import send_ooredoo_sms

def login_with_phone(request):

    if request.user.is_authenticated:
        return redirect('dashboard')

    if request.method == 'POST':
        form = PhoneLoginForm(request.POST)
        if form.is_valid():
            phone = form.cleaned_data['phone']
            otp = random.randint(1000, 9999)
            request.session['login_phone'] = phone
            cache.set(f'otp_{phone}', otp, timeout=300)
            sms_sent = send_ooredoo_sms(phone, otp)
            
            if sms_sent:
                messages.success(request, "OTP sent to your mobile number.")
                return redirect('verify_otp')
            else:
                messages.error(request, "Failed to send SMS. Please try again.")
    else:
        form = PhoneLoginForm()

    return render(request, 'registration/login_phone.html', {'form': form})


def verify_otp(request):
    phone = request.session.get('login_phone')
    if not phone:
        return redirect('login_phone')

    if request.method == 'POST':
        form = OTPVerificationForm(request.POST)
        if form.is_valid():
            user_otp = form.cleaned_data['otp']
            cached_otp = cache.get(f'otp_{phone}')

            if cached_otp and str(cached_otp) == str(user_otp):
                try:
                    user = User.objects.get(phone=phone)
                    user.backend = 'django.contrib.auth.backends.ModelBackend'
                    
                    login(request, user)
                    cache.delete(f'otp_{phone}')
                    if 'login_phone' in request.session:
                        del request.session['login_phone']
                    
                    messages.success(request, "Login Successful!")
                    return redirect('dashboard')
                except User.DoesNotExist:
                    messages.error(request, "User not found associated with this number.")
            else:
                messages.error(request, "Invalid or Expired OTP.")
    else:
        form = OTPVerificationForm()

    return render(request, 'registration/verify_otp.html', {'form': form, 'phone': phone})