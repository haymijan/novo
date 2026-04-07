from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, permission_required
from django.contrib import messages
from django.http import JsonResponse
from django.utils import timezone
from .models import Coupon, GiftCard, GiftCardTransaction
from .forms import CouponForm, GiftCardForm 


from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils.html import strip_tags

from django.db import transaction
from finance.gl.models import JournalEntry, JournalEntryItem, FinanceSettings

import barcode
from barcode.writer import ImageWriter
from io import BytesIO
import base64
from email.mime.image import MIMEImage

from pos.models import POSOrderPayment

# ==================== COUPON VIEWS ====================
@login_required
@permission_required('marketing.view_coupon', login_url='/admin/')
def coupon_list(request):
    coupons = Coupon.objects.all().order_by('-id')
    return render(request, 'marketing/coupon_list.html', {'coupons': coupons, 'title': 'Coupon Management'})

@login_required
@permission_required('marketing.add_coupon', login_url='/admin/')
def create_coupon(request):
    if request.method == 'POST':
        form = CouponForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Coupon created successfully!")
            return redirect('marketing:coupon_list')
    else:
        form = CouponForm()
    return render(request, 'marketing/coupon_form.html', {'form': form, 'title': 'Create New Coupon'})

@login_required
@permission_required('marketing.view_giftcard', login_url='/admin/')
def gift_card_list(request):
    gift_cards = GiftCard.objects.all().order_by('-id') 
    return render(request, 'marketing/gift_card_list.html', {'gift_cards': gift_cards, 'title': 'Gift Cards'})

@login_required
@permission_required('marketing.add_giftcard', login_url='/admin/')
def create_gift_card(request):
    if request.method == 'POST':
        form = GiftCardForm(request.POST)
        if form.is_valid():
            try:
                with transaction.atomic():
                    finance_settings = FinanceSettings.objects.first()
                    if not finance_settings:
                        messages.error(request, "Finance Settings missing!")
                        return redirect('marketing:gift_card_list')

                    cash_account = getattr(finance_settings, 'default_cash_account', None)
                    liability_account = getattr(finance_settings, 'default_gift_card_liability_account', None)

                    if not cash_account or not liability_account:
                        messages.error(request, "Default Cash or Liability account not set.")
                        return redirect('marketing:gift_card_list')

                    gift_card = form.save(commit=False)
                    gift_card.current_balance = gift_card.initial_value
                    gift_card.is_active = True
                    gift_card.save()

                    GiftCardTransaction.objects.create(
                        gift_card=gift_card,
                        amount=gift_card.initial_value,
                        transaction_type='reload',
                        reference='Direct Issuance',
                    )
                    je = JournalEntry.objects.create(
                        date=timezone.now().date(),
                        description=f"Gift Card Issued: {gift_card.code}",
                        created_by=request.user,
                        status='Posted'
                    )
                    JournalEntryItem.objects.create(
                        journal_entry=je,
                        account=cash_account,
                        debit=gift_card.initial_value,
                        credit=0
                    )
                    JournalEntryItem.objects.create(
                        journal_entry=je,
                        account=liability_account,
                        debit=0,
                        credit=gift_card.initial_value
                    )

                    messages.success(request, "Gift Card Issued & Posted to Accounts!")
                    return redirect('marketing:gift_card_list')
            
            except Exception as e:
                messages.error(request, f"Error: {e}")
    else:
        form = GiftCardForm()
    return render(request, 'marketing/gift_card_form.html', {'form': form, 'title': 'Issue Gift Card (Direct)'})

@login_required
@permission_required('marketing.add_giftcard', login_url='/admin/')
def generate_batch_cards(request):
    if request.method == 'POST':
        amount = request.POST.get('amount')
        quantity = int(request.POST.get('quantity', 10))
        
        try:
            with transaction.atomic():
                cards_created = []
                for _ in range(quantity):
                    card = GiftCard.objects.create(
                        initial_value=amount,
                        current_balance=amount,
                        is_active=False
                    )
                    cards_created.append(card)
                
                messages.success(request, f"{quantity} inactive cards generated successfully! Ready for printing.")
                return redirect('marketing:gift_card_list')
        except Exception as e:
            messages.error(request, f"Error: {e}")

    return render(request, 'marketing/batch_generate.html')

@login_required
def check_gift_card_balance(request):
    code = request.GET.get('code', '').strip()
    try:
        card = GiftCard.objects.get(code=code, is_active=True)
        if card.expiry_date and card.expiry_date < timezone.now().date():
             return JsonResponse({'status': 'error', 'message': 'Card Expired'})
             
        return JsonResponse({'status': 'success', 'balance': card.current_balance})
    except GiftCard.DoesNotExist:
        return JsonResponse({'status': 'error', 'message': 'Invalid Card Code'})
    
@login_required
def print_gift_card(request, pk):
    card = get_object_or_404(GiftCard, pk=pk)
    context = {
        'card': card,
        'company_name': 'NOVO ERP',
    }
    return render(request, 'marketing/print_gift_card.html', context)

@login_required
def email_gift_card(request, pk):
    card = get_object_or_404(GiftCard, pk=pk)
    
    if not card.customer or not card.customer.email:
        messages.error(request, "This customer does not have a valid email address.")
        return redirect('marketing:gift_card_list')
    try:
        buffer = BytesIO()
        Code128 = barcode.get_barcode_class('code128')
        barcode_obj = Code128(card.code, writer=ImageWriter())
        barcode_obj.write(buffer, options={"write_text": False}) 
        buffer.seek(0)
        image_data = buffer.getvalue()
        
    except Exception as e:
        print(f"Barcode generation error: {e}")
        image_data = None

    context = {
        'card': card,
        'company_name': 'EBANGLA',
    }

    subject = f"Your Digital Gift Card - {card.initial_value} TK"
    html_content = render_to_string('marketing/email_gift_card.html', context)
    text_content = strip_tags(html_content)
    
    try:
        email = EmailMultiAlternatives(
            subject, 
            text_content, 
            'noreply@yourdomain.com', 
            [card.customer.email]
        )
        email.attach_alternative(html_content, "text/html")
        if image_data:
            image = MIMEImage(image_data)
            image.add_header('Content-ID', '<barcode_image>') 
            email.attach(image)

        email.send()
        messages.success(request, f"Gift Card sent to {card.customer.email} successfully!")
    except Exception as e:
        messages.error(request, f"Failed to send email: {e}")
        
    return redirect('marketing:gift_card_list')

@login_required
def gift_card_detail(request, pk):
    card = get_object_or_404(GiftCard, pk=pk)

    transactions = GiftCardTransaction.objects.filter(gift_card=card).order_by('-date')

    context = {
        'card': card,
        'transactions': transactions,
        'title': f"Gift Card Details: {card.code}"
    }
    return render(request, 'marketing/gift_card_detail.html', context)