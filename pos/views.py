import json
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import JsonResponse
from django.db.models import Q, F, Sum
from decimal import Decimal

from products.models import Product
from sales.models import SalesOrder, SalesOrderItem
from stock.models import Stock, Warehouse, LotSerialNumber, InventoryTransaction 
from stock.services import StockService
from partners.models import Customer
from .models import POSSession, POSOrder, POSOrderItem, POSOrderPayment

from finance.cash.models import CashRegister, CashTransaction
from finance.banking.models import PaymentMethod, BankAccount, BankTransaction

from .forms import ReconciliationFormSet
from finance.gl.services import create_journal_entry
from finance.gl.models import ChartOfAccount, JournalEntry, JournalEntryItem, FinanceSettings

from django.contrib import messages
from django.utils import timezone
from django.http import HttpResponse
from django.contrib.contenttypes.models import ContentType
from django.db.models.functions import Coalesce

from marketing.models import Coupon, GiftCard, GiftCardTransaction 

DEFAULT_CURRENCY_SYMBOL = 'QAR '

#===============================================================================

def get_or_create_pos_session(request, warehouse):
    try:
        cash_payment_method = PaymentMethod.objects.filter(
            Q(warehouse=warehouse) | Q(warehouse__isnull=True),
            type='Cash',
            is_active=True
        ).first()
        if not cash_payment_method:
            raise PaymentMethod.DoesNotExist
    except PaymentMethod.DoesNotExist:
        raise Exception(f"Configuration Error: No active 'Cash' payment method found for warehouse '{warehouse.name}'. Please configure one in the admin.")
    cash_account = getattr(cash_payment_method, 'chart_of_account', None)
    if not cash_account:
        raise Exception(f"Configuration Error: The '{cash_payment_method.name}' payment method is not linked to a Chart of Account. Please fix it in the admin.")
    register_name = f"{request.user.username}'s Register"
    cash_register, created = CashRegister.objects.get_or_create(
        name=register_name, 
        defaults={
            'chart_of_account': cash_account,
            'warehouse': warehouse
        }
    )
    session, created = POSSession.objects.get_or_create(
        user=request.user,
        cash_register=cash_register,
        status='open',
        defaults={
            'opening_balance': 0.00
        }
    )
    return session

@login_required
def pos_view(request):

    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            cart = data.get('cart', [])
            customer_id = data.get('customer_id')
            discount = Decimal(str(data.get('discount', '0.00')))
            round_off_amount = Decimal(str(data.get('round_off_amount', '0.00')))
            
            payments_data = data.get('payments', [])
            coupon_code = data.get('coupon_code')

            if not cart:
                return JsonResponse({'status': 'error', 'message': 'Cart is empty.'}, status=400)

            user_warehouse = getattr(request.user, 'warehouse', None)
            if request.user.is_superuser and not user_warehouse:
                user_warehouse = Warehouse.objects.first()
            
            if not user_warehouse:
                return JsonResponse({'status': 'error', 'message': 'No warehouse assigned or available.'}, status=400)

            pos_session = get_or_create_pos_session(request, user_warehouse)
            
            if not pos_session:
                 return JsonResponse({'status': 'error', 'message': 'Active POS session required.'}, status=400)

            customer = get_object_or_404(Customer, id=customer_id) if customer_id else None

            with transaction.atomic():
                total_amount = sum(Decimal(str(item['quantity'])) * Decimal(str(item['sale_price'])) for item in cart)
                
                if coupon_code:
                    try:
                        coupon = Coupon.objects.get(code=coupon_code, active=True)
                        if coupon.is_valid():
                            coupon.used_count += 1
                            coupon.save()
                        else:
                            raise ValueError("Invalid or expired coupon applied.")
                    except Coupon.DoesNotExist:
                        pass 

                if discount > 0:
                    if total_amount == 0:
                         return JsonResponse({'status': 'error', 'message': "Cannot apply discount on zero amount."}, status=400)
                    
                    if discount > total_amount:
                         return JsonResponse({'status': 'error', 'message': "Discount cannot be greater than the total amount."}, status=400)

                    discount_percentage = (discount / total_amount) * 100
                    user_max_discount = getattr(request.user, 'max_discount_percentage', Decimal('0.00'))
                    
                    if not request.user.is_superuser and discount_percentage > user_max_discount:
                        return JsonResponse({
                            'status': 'error', 
                            'message': f"You can only give up to {user_max_discount}% discount. Requested: {discount_percentage:.2f}%"
                        }, status=400)

                net_amount = total_amount - discount - round_off_amount

                pos_order = POSOrder.objects.create(
                    pos_session=pos_session,
                    customer=customer,
                    warehouse=user_warehouse,
                    order_date=timezone.now(),
                    total_amount=total_amount,
                    discount=discount,
                    round_off_amount=round_off_amount,
                    net_amount=net_amount,
                    status='paid'
                )

                sales_order = SalesOrder.objects.create(
                    customer=customer,
                    warehouse=user_warehouse,
                    order_date=timezone.now(),
                    expected_delivery_date=timezone.now(),
                    status='delivered',
                    discount=discount,
                    round_off_amount=round_off_amount,
                    notes=f"POS Order #{pos_order.id}. Coupon: {coupon_code if coupon_code else 'N/A'}",
                    user=request.user,
                    total_amount=net_amount
                )

                total_gc_liability = Decimal('0.00')
                total_sales_revenue_items = Decimal('0.00')
                total_cost_of_goods_sold = Decimal('0.00')

                for item in cart:
                    product = Product.objects.get(id=item['id'])
                    qty = int(item['quantity'])
                    price = Decimal(str(item['sale_price']))
                    lot_id = item.get('lot_serial_id')
                    gift_card_serial = item.get('serial_number')

                    lot_obj = None
                    if lot_id:
                        lot_obj = LotSerialNumber.objects.get(id=lot_id)
                    
                    is_gift_card = getattr(product, 'product_type', 'standard') == 'gift_card'
                    line_total = price * qty

                    if is_gift_card:
                        if gift_card_serial:
                            try:
                                gc_obj = GiftCard.objects.get(code=gift_card_serial)
                                if gc_obj.is_active:
                                    raise ValueError(f"Gift Card {gift_card_serial} is already active!")
                                
                                gc_obj.is_active = True
                                gc_obj.save()

                                GiftCardTransaction.objects.create(
                                    gift_card=gc_obj,
                                    amount=price,
                                    transaction_type='reload',
                                    reference=f"POS Activation #{pos_order.id}"
                                )
                                total_gc_liability += line_total

                            except GiftCard.DoesNotExist:
                                raise ValueError(f"Invalid Gift Card Code: {gift_card_serial}")
                        else:
                             total_gc_liability += line_total
                    else:
                        total_sales_revenue_items += line_total

                        # === UPDATED STOCK DEDUCTION LOGIC START ===
                        if product.tracking_method in ['lot', 'serial']:
                            qty_to_deduct = qty
                            
                            # Case A: User selected a specific Lot
                            if lot_obj:
                                if lot_obj.quantity < qty:
                                    raise ValueError(f"Insufficient stock for {product.name} in batch {lot_obj.lot_number}")
                                
                                # Use StockService to handle both Stock and Lot updates + Transaction Log
                                StockService.change_stock(
                                    product=product,
                                    warehouse=user_warehouse,
                                    quantity_change=-qty,
                                    transaction_type='sale',
                                    user=request.user,
                                    content_object=pos_order,
                                    location=lot_obj.location,
                                    lot_serial=lot_obj
                                )
                            
                            # Case B: No Lot selected -> Auto-deduct (FIFO/FEFO)
                            else:
                                available_lots = LotSerialNumber.objects.filter(
                                    product=product,
                                    location__warehouse=user_warehouse,
                                    quantity__gt=0
                                ).order_by('expiration_date', 'created_at')

                                total_available = sum(l.quantity for l in available_lots)
                                if total_available < qty:
                                    raise ValueError(f"Insufficient stock for {product.name}. Available in lots: {total_available}")

                                for lot in available_lots:
                                    if qty_to_deduct <= 0:
                                        break
                                    
                                    deduct_amount = min(lot.quantity, qty_to_deduct)
                                    
                                    StockService.change_stock(
                                        product=product,
                                        warehouse=user_warehouse,
                                        quantity_change=-deduct_amount,
                                        transaction_type='sale',
                                        user=request.user,
                                        content_object=pos_order,
                                        location=lot.location,
                                        lot_serial=lot,
                                        notes=f"Auto-deducted from Lot {lot.lot_number}"
                                    )
                                    
                                    # Keep reference to the first lot for the line item record
                                    if lot_obj is None:
                                        lot_obj = lot
                                    
                                    qty_to_deduct -= deduct_amount

                        else:
                            # Case C: Non-tracked product
                            StockService.change_stock(
                                product=product,
                                warehouse=user_warehouse,
                                quantity_change=-qty,
                                transaction_type='sale',
                                user=request.user,
                                content_object=pos_order,
                                location=user_warehouse.locations.first(), # Default location
                                notes="Standard product sale"
                            )
                        # === UPDATED STOCK DEDUCTION LOGIC END ===

                    POSOrderItem.objects.create(
                        pos_order=pos_order,
                        product=product,
                        quantity=qty,
                        unit_price=price,
                        lot_serial=lot_obj
                    )

                    cost_price = Decimal('0.00')
                    if lot_obj:
                        cost_price = lot_obj.cost_price
                    elif product.cost_price:
                        cost_price = product.cost_price

                    if not is_gift_card:
                        total_cost_of_goods_sold += (cost_price * qty)

                    SalesOrderItem.objects.create(
                        sales_order=sales_order,
                        product=product,
                        quantity=qty,
                        unit_price=price,
                        cost_price=cost_price,
                        quantity_fulfilled=qty
                    )
                    
                    # NOTE: Removed manual InventoryTransaction.objects.create(...) 
                    # because StockService.change_stock already creates it.

                sales_order.save()

                total_paid_in_request = Decimal('0.00')
                
                for p in payments_data:
                    method_id = p.get('id')
                    amount = Decimal(str(p.get('amount')))
                    payment_method = PaymentMethod.objects.get(id=method_id)
                    used_gift_card = None
                    
                    if payment_method.type == 'Gift Card':
                        card_code = p.get('card_code')
                        if not card_code:
                            raise ValueError(f"Gift card code missing")
                        
                        used_gift_card = GiftCard.objects.get(code=card_code, is_active=True)
                        if used_gift_card.current_balance < amount:
                            raise ValueError(f"Insufficient balance in Gift Card {card_code}")
                        
                        used_gift_card.current_balance -= amount
                        used_gift_card.save()

                        GiftCardTransaction.objects.create(
                            gift_card=used_gift_card,
                            amount=amount,
                            transaction_type='purchase',
                            reference=f"POS Payment #{pos_order.id}"
                        )

                    POSOrderPayment.objects.create(
                        pos_order=pos_order,
                        payment_method=payment_method,
                        amount=amount,
                        gift_card=used_gift_card
                    )
                    
                    total_paid_in_request += amount

                    # Update Cash Register Logic
                    if hasattr(payment_method, 'type') and payment_method.type == 'Cash':
                        if pos_session.cash_register:
                            pos_session.cash_register.current_balance += amount
                            pos_session.cash_register.save(update_fields=['current_balance'])

                # --- Accounting Logic (Manual Split) ---
                finance_settings = FinanceSettings.objects.first()
                if finance_settings:
                    sales_account = finance_settings.default_sales_revenue_account
                    gc_liability_account = finance_settings.default_gift_card_liability_account
                    default_cash_account = finance_settings.default_cash_account 
                    
                    cogs_account = finance_settings.default_cogs_account
                    inventory_account = finance_settings.default_inventory_account

                    je = JournalEntry.objects.create(
                        date=timezone.now(),
                        description=f"POS Sale #{pos_order.id}",
                        status='Posted',
                        created_by=request.user,
                        warehouse=user_warehouse
                    )
                    
                    # 1. Credit: Sales Revenue
                    revenue_amount = total_sales_revenue_items 
                    if discount > 0:
                        revenue_amount = revenue_amount - discount
                    if round_off_amount > 0:
                        revenue_amount = revenue_amount - round_off_amount

                    if revenue_amount > 0 and sales_account:
                        JournalEntryItem.objects.create(
                            journal_entry=je, account=sales_account, debit=0, credit=revenue_amount
                        )
                    
                    # 2. Credit: Liability (Gift Card Sales)
                    if total_gc_liability > 0 and gc_liability_account:
                         JournalEntryItem.objects.create(
                            journal_entry=je, account=gc_liability_account, debit=0, credit=total_gc_liability
                        )

                    # 3. Debit: COGS & Credit: Inventory Asset
                    if total_cost_of_goods_sold > 0 and cogs_account and inventory_account:
                        JournalEntryItem.objects.create(
                            journal_entry=je, account=cogs_account, debit=total_cost_of_goods_sold, credit=0,
                            description=f"COGS for POS #{pos_order.id}"
                        )
                        JournalEntryItem.objects.create(
                            journal_entry=je, account=inventory_account, debit=0, credit=total_cost_of_goods_sold,
                            description=f"Inventory deduction for POS #{pos_order.id}"
                        )

                    # 4. Debit: Payments (Cash/Bank/GiftCard)
                    for p in payments_data:
                        method_id = p.get('id')
                        amount = Decimal(str(p.get('amount')))
                        pm = PaymentMethod.objects.get(id=method_id)
                        
                        debit_account = pm.chart_of_account or default_cash_account
                        if debit_account:
                            JournalEntryItem.objects.create(
                                journal_entry=je, account=debit_account, debit=amount, credit=0
                            )
                
            return JsonResponse({'status': 'success', 'order_id': pos_order.id})

        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)}, status=400)

    user_warehouse = getattr(request.user, 'warehouse', None)
    if not user_warehouse and request.user.is_superuser:
        user_warehouse = Warehouse.objects.first()

    #payment_methods = []
    payment_methods = PaymentMethod.objects.none()
    if user_warehouse:
        payment_methods = PaymentMethod.objects.filter(
            Q(warehouse=user_warehouse) | Q(warehouse__isnull=True), 
            is_available_for_pos=True
        )
    
    products_qs = Product.objects.filter(is_active=True).select_related()
    products_data = []
    
    for p in products_qs:
        img_url = p.image.url if p.image else ''
        qty = 0
        if hasattr(p, 'total_quantity'):
            qty = p.total_quantity
        
        code = getattr(p, 'product_code', '') 
        barcode = getattr(p, 'barcode', '')
        p_type = getattr(p, 'product_type', 'standard') 

        products_data.append({
            'id': p.id,
            'name': p.name,
            'code': code,      
            'barcode': barcode,
            'sale_price': p.sale_price,
            'total_quantity': qty,
            'image': img_url,
            'tracking_method': p.tracking_method,
            'product_type': p_type
        })

    context = {
        'title': 'Point of Sale',

        'products_json': json.dumps(products_data, default=str), 

        'payment_methods': payment_methods, 
        
        'payment_methods_json': json.dumps(list(payment_methods.values('id', 'name', 'type')), default=str),

        'customers': Customer.objects.filter(is_active=True)[:20],
        
        'DEFAULT_CURRENCY_SYMBOL': DEFAULT_CURRENCY_SYMBOL, 
    }
    return render(request, 'pos/pos.html', context)

@login_required
def get_products_for_pos(request):
    warehouse = getattr(request.user, 'warehouse', None)
    if not warehouse:
        if request.user.is_superuser:
            warehouse = Warehouse.objects.first()
        else:
            return JsonResponse({'error': 'User not assigned to a warehouse'}, status=400)
    if not warehouse:
         return JsonResponse({'error': 'No warehouse available.'}, status=400)

    products_in_stock = {}

    lots = LotSerialNumber.objects.filter(
        location__warehouse=warehouse, 
        quantity__gt=0
    ).select_related('product', 'product__category')

    for lot in lots:
        product = lot.product
        if product.id not in products_in_stock:
            image_url = product.image.url if product.image else None
            p_type = getattr(product, 'product_type', 'standard')
            products_in_stock[product.id] = {
                'id': product.id,
                'name': product.name,
                'code': product.product_code,
                'category': product.category.name if product.category else 'N/A',
                'sale_price': str(product.sale_price),
                'tracking_method': product.tracking_method,
                'image_url': image_url,
                'total_quantity': 0,
                'lots': [],
                'product_type': p_type
            }
        products_in_stock[product.id]['total_quantity'] += lot.quantity
        products_in_stock[product.id]['lots'].append({
            'id': lot.id,
            'lot_number': lot.lot_number,
            'quantity': lot.quantity,
            'expiration_date': lot.expiration_date.strftime('%Y-%m-%d') if lot.expiration_date else None
        })

    non_tracked_stocks = Stock.objects.filter(
        warehouse=warehouse,
        quantity__gt=0,
        product__tracking_method='none'
    ).select_related('product', 'product__category')

    for stock in non_tracked_stocks:
        product = stock.product
        if product.id not in products_in_stock:
            image_url = product.image.url if product.image else None
            p_type = getattr(product, 'product_type', 'standard')
            products_in_stock[product.id] = {
                'id': product.id,
                'name': product.name,
                'code': product.product_code,
                'category': product.category.name if product.category else 'N/A',
                'sale_price': str(product.sale_price),
                'tracking_method': product.tracking_method,
                'image_url': image_url,
                'total_quantity': stock.quantity,
                'lots': [],
                'product_type': p_type
            }
    
    gift_cards = Product.objects.filter(product_type='gift_card', is_active=True)
    
    for product in gift_cards:
        if product.id not in products_in_stock:
             image_url = product.image.url if product.image else None
             products_in_stock[product.id] = {
                'id': product.id,
                'name': product.name,
                'code': product.product_code or 'GC',
                'category': product.category.name if product.category else 'Gift Cards',
                'sale_price': str(product.sale_price),
                'tracking_method': 'none',
                'image_url': image_url,
                'total_quantity': 9999,
                'lots': [],
                'product_type': 'gift_card' # <--- Added
            }

    return JsonResponse(list(products_in_stock.values()), safe=False)


@login_required
def get_customers_for_pos(request):
    term = request.GET.get('term', '').strip()
    customers = Customer.objects.filter(is_active=True)
    
    if term:
        customers = customers.filter(
            Q(name__icontains=term) | 
            Q(phone__icontains=term)
        )
    
    results = []
    for c in customers[:20]:
        text = f"{c.name} ({c.phone})" if c.phone else c.name
        results.append({
            'id': c.id,
            'text': text,
            'name': c.name,
            'phone': c.phone
        })
    
    return JsonResponse({'results': results}, safe=False)

@login_required
def pos_create_customer(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            phone = data.get('phone', '').strip()
            name = data.get('name', '').strip()
            
            if not phone and not name:
                return JsonResponse({'status': 'error', 'message': 'Phone number or Name is required.'}, status=400)
            
            if phone:
                existing = Customer.objects.filter(phone=phone).first()
                if existing:
                    return JsonResponse({
                        'status': 'success',
                        'customer': {
                            'id': existing.id,
                            'text': f"{existing.name} ({existing.phone})",
                            'name': existing.name,
                            'phone': existing.phone
                        },
                        'message': 'Customer already exists.'
                    })
            
            if not name:
                name = f"Guest-{phone}" if phone else "Walk-in Customer"

            new_customer = Customer.objects.create(
                name=name,
                phone=phone,
                is_active=True
            )
            
            return JsonResponse({
                'status': 'success',
                'customer': {
                    'id': new_customer.id,
                    'text': f"{new_customer.name} ({new_customer.phone})",
                    'name': new_customer.name,
                    'phone': new_customer.phone
                }
            })
            
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)}, status=400)
    
    return JsonResponse({'status': 'error', 'message': 'Invalid method'}, status=405)

@login_required
def pos_session_close(request, pk):
    session = get_object_or_404(POSSession, pk=pk, status='open')
    warehouse = session.cash_register.warehouse

    # ১. পেমেন্ট মেথড অনুযায়ী এক্সপেক্টেড টোটাল বের করা
    expected_totals_qs = session.pos_orders.all() \
                            .values(
                                'payments__payment_method_id', 
                                'payments__payment_method__name',
                                'payments__payment_method__type',
                                'payments__payment_method__chart_of_account__id',
                                'payments__payment_method__main_chart_of_account__id'
                            ) \
                            .annotate(total=Sum('payments__amount')) \
                            .order_by('payments__payment_method__name')

    expected_totals = []
    for item in expected_totals_qs:
        if item['total']: 
            expected_totals.append({
                'payment_method_id': item['payments__payment_method_id'],
                'payment_method_name': item['payments__payment_method__name'],
                'payment_method_type': item['payments__payment_method__type'], 
                'expected_amount': item['total'],
                'clearing_account_id': item['payments__payment_method__chart_of_account__id'],
                'main_account_id': item['payments__payment_method__main_chart_of_account__id'],
            })

    if request.method == 'POST':
        formset = ReconciliationFormSet(request.POST, prefix='recon')
        if formset.is_valid():
            try:
                with transaction.atomic():
                    total_difference = Decimal(0)
                    
                    # Finance Settings Check
                    settings = FinanceSettings.objects.first()
                    if not settings or not settings.default_cash_difference_account:
                        messages.error(request, "Accounting setup error: 'Cash Over/Short' Account is not set in Finance Configuration.")
                        return redirect('pos:pos_session_list')

                    over_short_account = settings.default_cash_difference_account

                    # ২. প্রতিটি পেমেন্ট মেথড প্রসেস করা
                    for form_data, expected_data in zip(formset.cleaned_data, expected_totals):
                        counted = form_data['counted_amount']
                        expected = expected_data['expected_amount']
                        difference = counted - expected
                        total_difference += difference
                        
                        payment_method_name = expected_data['payment_method_name']
                        c_id = expected_data.get('clearing_account_id')
                        m_id = expected_data.get('main_account_id')

                        if not c_id or not m_id:
                            raise Exception(f"Payment Method '{payment_method_name}' is missing Chart of Account configuration (Clearing or Main Account). Please set this in Admin > Payment Methods.")

                        clearing_account = ChartOfAccount.objects.get(id=c_id)
                        main_account = ChartOfAccount.objects.get(id=m_id)
                        # --------------------------------------

                        recon_desc = f"POS Session #{session.pk} Close: {payment_method_name}"

                        # Journal Entry Creation
                        recon_journal = JournalEntry.objects.create(
                            date=timezone.now().date(),
                            description=recon_desc,
                            created_by=request.user,
                            warehouse=warehouse,
                            content_object=session
                        )
                        
                        # Debit: Main Account (Cash/Bank/Liability)
                        JournalEntryItem.objects.create(journal_entry=recon_journal, account=main_account, debit=counted, credit=0)
                        
                        # Handle Over/Short (Difference)
                        if difference > 0:
                            JournalEntryItem.objects.create(journal_entry=recon_journal, account=over_short_account, debit=0, credit=difference)
                        elif difference < 0:
                            JournalEntryItem.objects.create(journal_entry=recon_journal, account=over_short_account, debit=abs(difference), credit=0)
                        
                        # Credit: Clearing Account
                        JournalEntryItem.objects.create(journal_entry=recon_journal, account=clearing_account, debit=0, credit=expected)
                        
                        # Update Journal Header Totals
                        recon_journal.total_debit = counted + (abs(difference) if difference < 0 else 0)
                        recon_journal.total_credit = expected + (difference if difference > 0 else 0)
                        recon_journal.status = 'Posted'
                        recon_journal.save()
                        
                        transaction_description = f"Auto-transfer from Session #{session.pk} - {payment_method_name}"
                        
                        # ৩. ক্যাশ বা ব্যাংক ট্রানজেকশন (যদি টাইপ Cash/Bank হয়)
                        if expected_data['payment_method_type'] == 'Cash':
                            seller_register = session.cash_register
                            
                            # Cash Out from Drawer
                            CashTransaction.objects.create(
                                register=seller_register,
                                transaction_date=timezone.now().date(),
                                transaction_type='cash_out',
                                amount=expected,
                                description=f"Transfer to Head Office (Session #{session.pk})",
                                created_by=request.user,
                                content_type=ContentType.objects.get_for_model(session),
                                object_id=session.pk
                            )
                            
                            seller_register.current_balance -= expected
                            seller_register.save(update_fields=['current_balance'])
                            
                            # Cash In to Main Safe
                            main_cash_register = CashRegister.objects.filter(chart_of_account=main_account).first()
                            if not main_cash_register:
                                raise Exception(f"No Cash Register found linked to the Main Cash Account ({main_account.name}).")

                            CashTransaction.objects.create(
                                register=main_cash_register,
                                transaction_date=timezone.now().date(),
                                transaction_type='cash_in',
                                amount=counted,
                                description=transaction_description,
                                created_by=request.user,
                                content_type=ContentType.objects.get_for_model(session),
                                object_id=session.pk
                            )
                            main_cash_register.current_balance += counted
                            main_cash_register.save(update_fields=['current_balance'])

                        elif expected_data['payment_method_type'] == 'Bank':
                            main_bank_account = BankAccount.objects.filter(chart_of_account=main_account).first()
                            if not main_bank_account:
                                raise Exception(f"No Bank Account found linked to the Main Bank Account ({main_account.name}).")

                            BankTransaction.objects.create(
                                bank_account=main_bank_account,
                                transaction_date=timezone.now().date(),
                                transaction_type='deposit',
                                amount=counted,
                                description=transaction_description,
                                created_by=request.user,
                                content_type=ContentType.objects.get_for_model(session),
                                object_id=session.pk
                            )

                    session.status = 'closed'
                    session.end_time = timezone.now()
                    session.expected_balance = sum(e['expected_amount'] for e in expected_totals)
                    session.counted_balance = sum(f['counted_amount'] for f in formset.cleaned_data)
                    session.difference = total_difference
                    session.save()

                    messages.success(request, f"Session #{session.pk} has been successfully closed and reconciled.")
                    return redirect('pos:pos_session_list')

            except Exception as e:
                messages.error(request, f"Error during reconciliation: {e}")
        
    else:
        initial_data = [{
            'payment_method_id': e['payment_method_id'],
            'payment_method_name': e['payment_method_name'],
            'expected_amount': e['expected_amount'],
            'counted_amount': e['expected_amount'],
            'difference': 0
        } for e in expected_totals]
        formset = ReconciliationFormSet(initial=initial_data, prefix='recon')

    context = {
        'title': f'Reconcile Session #{session.pk}',
        'session': session,
        'formset': formset,
    }
    return render(request, 'pos/pos_session_close.html', context)

@login_required
def pos_receipt_view(request, order_id):
    order = get_object_or_404(POSOrder, id=order_id)
    payments = order.payments.all()
    total_paid = payments.aggregate(total=Sum('amount'))['total'] or 0
    cash_paid = payments.filter(payment_method__type='Cash').aggregate(total=Sum('amount'))['total'] or 0
    card_paid = payments.filter(payment_method__type='Bank').aggregate(total=Sum('amount'))['total'] or 0
    change_due = total_paid - order.net_amount
    context = {
        'order': order,
        'DEFAULT_CURRENCY_SYMBOL': DEFAULT_CURRENCY_SYMBOL,
        'cash_paid': cash_paid,
        'card_paid': card_paid,
        'change_due': change_due if change_due > 0 else 0
    }
    return render(request, 'pos/pos_receipt.html', context)

@login_required
def pos_session_list(request):
    warehouse = getattr(request.user, 'warehouse', None)
    sessions = POSSession.objects.all().order_by('-start_time')
    if not request.user.is_superuser and warehouse:
        sessions = sessions.filter(cash_register__warehouse=warehouse)
    context = {
        'title': 'POS Sessions',
        'sessions': sessions
    }
    return render(request, 'pos/pos_session_list.html', context)

@login_required
def pos_session_report(request, pk):
    session = get_object_or_404(POSSession, pk=pk)
    orders = POSOrder.objects.filter(pos_session=session).order_by('-order_date') 
    session_summary = orders.aggregate(
        total_discount=Coalesce(Sum('discount'), Decimal(0)),
        total_sales_net=Coalesce(Sum('net_amount'), Decimal(0)) 
    )
    payment_summary = POSOrderPayment.objects.filter(pos_order__pos_session=session) \
        .values('payment_method__name') \
        .annotate(total_amount=Sum('amount')) \
        .order_by('-total_amount')

    product_summary = POSOrderItem.objects.filter(pos_order__pos_session=session) \
        .values('product__name') \
        .annotate(total_qty=Sum('quantity'), total_value=Sum(F('quantity') * F('unit_price'))) \
        .order_by('-total_qty')

    context = {
        'title': f'Report for Session #{session.pk}',
        'session': session,
        'orders': orders,
        'payment_summary': payment_summary,
        'product_summary': product_summary,
        'DEFAULT_CURRENCY_SYMBOL': DEFAULT_CURRENCY_SYMBOL,
        'total_session_discount': session_summary['total_discount'],
        'total_session_sales': session_summary['total_sales_net'],
    }
    return render(request, 'pos/pos_session_report.html', context)

@login_required
def pos_add_to_cart(request):
    return JsonResponse({'error': 'Deprecated function'}, status=400)
@login_required
def pos_remove_from_cart(request):
    return JsonResponse({'error': 'Deprecated function'}, status=400)
@login_required
def pos_get_cart(request):
    return JsonResponse({'error': 'Deprecated function'}, status=400)
@login_required
def pos_checkout_view(request):
    return JsonResponse({'error': 'Deprecated function'}, status=400)