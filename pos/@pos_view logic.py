@login_required
def pos_view(request):
    """
    POS Sales View.
    Features: Stock, Accounting, Cash Register, Coupon & Gift Card Integration.
    [UPDATED]: Gift Card Activation & Liability Accounting Logic Added.
    """
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            cart = data.get('cart', [])
            customer_id = data.get('customer_id')
            discount = Decimal(str(data.get('discount', '0.00')))
            # ১. রাউন্ডিং অ্যামাউন্ট রিসিভ করা
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

            pos_session = None
            if 'get_or_create_pos_session' in globals():
                pos_session = get_or_create_pos_session(request, user_warehouse)
            
            if not pos_session:
                pos_session = POSSession.objects.filter(user=request.user, warehouse=user_warehouse, status='open').first()
                if not pos_session:
                      pos_session = POSSession.objects.create(
                          user=request.user, 
                          warehouse=user_warehouse, 
                          opening_balance=0,
                          status='open'
                      )

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
                        
                        if lot_obj:
                            if lot_obj.quantity < qty:
                                raise ValueError(f"Insufficient stock for {product.name} in batch {lot_obj.lot_number}")
                            lot_obj.quantity -= qty
                            lot_obj.save()
                        else:
                            try:
                                stock = Stock.objects.get(product=product, warehouse=user_warehouse)
                                if stock.quantity < qty:
                                    raise ValueError(f"Insufficient stock for {product.name}")
                                stock.quantity -= qty
                                stock.save()
                            except Stock.DoesNotExist:
                                pass
                    
                    POSOrderItem.objects.create(
                        pos_order=pos_order,
                        product=product,
                        quantity=qty,
                        unit_price=price,
                        lot_serial=lot_obj
                    )

                    cost_price = 0
                    if lot_obj:
                        cost_price = lot_obj.cost_price
                    elif product.cost_price:
                        cost_price = product.cost_price

                    SalesOrderItem.objects.create(
                        sales_order=sales_order,
                        product=product,
                        quantity=qty,
                        unit_price=price,
                        cost_price=cost_price,
                        lot_sold_from=lot_obj,
                        quantity_fulfilled=qty
                    )

                    if not is_gift_card:
                        source_loc = None
                        if lot_obj:
                            source_loc = lot_obj.location
                        else:
                            source_loc = user_warehouse.locations.first()

                        InventoryTransaction.objects.create(
                            product=product,
                            warehouse=user_warehouse,
                            transaction_type='sale',
                            quantity=-qty,
                            lot_serial=lot_obj,
                            user=request.user,
                            content_type=ContentType.objects.get_for_model(pos_order),
                            object_id=pos_order.id,
                            notes=f"POS Order #{pos_order.id}",
                            source_location=source_loc,
                            from_warehouse=user_warehouse
                        )
                
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

                    if hasattr(payment_method, 'type') and payment_method.type == 'Cash':
                        if pos_session.cash_register:
                            pos_session.cash_register.current_balance += amount
                            pos_session.cash_register.save(update_fields=['current_balance'])

                finance_settings = FinanceSettings.objects.first()
                if finance_settings:
                    sales_account = finance_settings.default_sales_revenue_account
                    gc_liability_account = finance_settings.default_gift_card_liability_account
                    default_cash_account = finance_settings.default_cash_account 

                    je = JournalEntry.objects.create(
                        date=timezone.now(),
                        description=f"POS Sale #{pos_order.id}",
                        status='Posted',
                        created_by=request.user
                    )
                    
                    revenue_amount = total_sales_revenue_items 
                    if discount > 0:
                        revenue_amount = revenue_amount - discount
                    if round_off_amount > 0:
                        revenue_amount = revenue_amount - round_off_amount

                    if revenue_amount > 0 and sales_account:
                        JournalEntryItem.objects.create(
                            journal_entry=je, account=sales_account, debit=0, credit=revenue_amount
                        )
                    
                    if total_gc_liability > 0 and gc_liability_account:
                         JournalEntryItem.objects.create(
                            journal_entry=je, account=gc_liability_account, debit=0, credit=total_gc_liability
                        )

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
    
    payment_methods = []
    if user_warehouse:
        payment_methods = PaymentMethod.objects.filter(
            Q(warehouse=user_warehouse) | Q(warehouse__isnull=True), 
            is_active=True
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
        'DEFAULT_CURRENCY_SYMBOL': 'QAR', 
        'products_json': products_data,
        'payment_methods': payment_methods,
        'customers': Customer.objects.filter(is_active=True)[:20]
    }
    return render(request, 'pos/pos.html', context)