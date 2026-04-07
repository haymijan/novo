from django.db import transaction
from django.core.exceptions import ValidationError
from django.db.models import Sum
from decimal import Decimal
from django.utils import timezone

from stock.models import LotSerialNumber, Location
from stock.services import StockService
from .models import SalesOrder, SalesOrderItem, SalesOrderItemAllocation, SalesPayment, Shipment, SalesReturn
from marketing.models import GiftCard
from finance.gl.models import JournalEntry, JournalEntryItem, FinanceSettings

from finance.ar.models import CustomerInvoice


class SalesService:
    
    @staticmethod
    def create_draft_order(user, warehouse, order_data, items_data):
        """Step 1: Create Order in Draft State"""
        with transaction.atomic():
            valid_fields = {f.name for f in SalesOrder._meta.get_fields()}
            model_data = {k: v for k, v in order_data.items() if k in valid_fields}
            tax_amount = Decimal(order_data.get('tax_amount', 0) or 0)
            shipping_cost = Decimal(order_data.get('shipping_cost', 0) or 0)
            discount_val = Decimal(order_data.get('discount', 0) or 0)
            round_off = Decimal(order_data.get('round_off_amount', 0) or 0)

            sales_order = SalesOrder(**model_data)
            sales_order.user = user
            sales_order.warehouse = warehouse
            sales_order.status = 'draft'
            sales_order.save()

            total_items_amount = Decimal('0.00')

            for item_data in items_data:
                if not item_data: continue

                item_data.pop('sales_order', None)
                item_data.pop('DELETE', None)
                
                sales_order_item = SalesOrderItem(sales_order=sales_order, **item_data)
                
                if sales_order_item.product:
                    sales_order_item.cost_price = sales_order_item.product.cost_price
                
                sales_order_item.save()
                total_items_amount += sales_order_item.subtotal

            sales_order.tax_amount = tax_amount
            sales_order.shipping_cost = shipping_cost
            sales_order.discount = discount_val
            sales_order.round_off_amount = round_off
            
            gross_total = total_items_amount + tax_amount + shipping_cost
            sales_order.total_amount = gross_total - discount_val - round_off
            
            sales_order.save()

            return sales_order

    @staticmethod
    def confirm_sales_order(order_id, user):
        """Step 2: Confirm Order"""
        sales_order = SalesOrder.objects.get(id=order_id)
        
        if sales_order.status != 'draft':
            raise ValidationError("Only draft orders can be confirmed.")

        with transaction.atomic():
            sales_order.status = 'confirmed'
            sales_order.save()

            settings_obj = FinanceSettings.objects.first()
            if settings_obj and settings_obj.default_sales_revenue_account:
                CustomerInvoice.objects.get_or_create(
                    sales_order=sales_order,
                    defaults={
                        'customer': sales_order.customer,
                        'invoice_date': sales_order.order_date.date(),
                        'due_date': sales_order.order_date.date(),
                        'total_amount': sales_order.total_amount,
                        'status': 'Submitted',
                        'created_by': user,
                        'revenue_account': settings_obj.default_sales_revenue_account
                    }
                )

            SalesService._create_invoice_journal(sales_order, user)
        
        return sales_order

    @staticmethod
    def process_payment(order_id, amount, payment_method, user, reference='', gift_card_code=None):
        """Step 3: Process Payment (Separate from Order Creation)"""
        sales_order = SalesOrder.objects.get(id=order_id)
        
        with transaction.atomic():
            # Gift Card Logic
            if gift_card_code:
                try:
                    gc = GiftCard.objects.get(code=gift_card_code, is_active=True)
                    if gc.current_balance < amount:
                        raise ValidationError("Insufficient Gift Card Balance")
                    gc.current_balance -= amount
                    gc.save()
                except GiftCard.DoesNotExist:
                    raise ValidationError("Invalid Gift Card")

            payment = SalesPayment.objects.create(
                sales_order=sales_order,
                payment_method=payment_method,
                amount=amount,
                reference=reference,
                recorded_by=user
            )

            total_paid = sum(p.amount for p in sales_order.payments.all())
            if total_paid >= sales_order.total_amount:
                sales_order.payment_status = 'paid'
            elif total_paid > 0:
                sales_order.payment_status = 'partial'
            sales_order.save()
            SalesService._create_payment_journal(sales_order, payment, user)

        return payment

    @staticmethod
    def create_shipment_and_fulfill(order_id, warehouse, user, tracking_number=''):
        """Step 4: Fulfillment (Deduct Stock, Mark Delivered)"""
        sales_order = SalesOrder.objects.get(id=order_id)
        

        if sales_order.status not in ['confirmed', 'processing', 'partially_delivered', 'packaging']:
            raise ValidationError("Order is not ready for fulfillment.")

        with transaction.atomic():

            shipment = Shipment.objects.create(
                sales_order=sales_order,
                warehouse=warehouse,
                tracking_number=tracking_number,
                status='shipped',
                shipped_date=timezone.now()
            )

            total_shipment_cogs = Decimal('0.00')
            items_shipped_count = 0

            for item in sales_order.items.all():
                qty_needed = item.quantity - item.quantity_fulfilled
                if qty_needed <= 0: continue

                shipment_cost_accumulated = Decimal('0.00')
                fulfilled_now = 0

                if item.product.tracking_method in ['lot', 'serial']:
                    available_lots = LotSerialNumber.objects.filter(
                        product=item.product,
                        location__warehouse=warehouse,
                        quantity__gt=0
                    ).order_by('expiration_date', 'created_at')

                    remaining_qty = qty_needed
                    
                    for lot in available_lots:
                        if remaining_qty <= 0: break
                        take_qty = min(lot.quantity, remaining_qty)

                        lot_cost = lot.cost_price if lot.cost_price else item.product.cost_price
                        shipment_cost_accumulated += (take_qty * lot_cost)

                        StockService.change_stock(
                            product=item.product,
                            warehouse=warehouse,
                            quantity_change=-take_qty,
                            transaction_type='sale',
                            user=user,
                            content_object=sales_order,
                            location=lot.location,
                            lot_serial=lot,
                            notes=f"Shipped via Shipment #{shipment.id}"
                        )
                        
                        SalesOrderItemAllocation.objects.create(
                            sales_order_item=item,
                            lot=lot,
                            quantity=take_qty
                        )
                        remaining_qty -= take_qty
                    
                    fulfilled_now = qty_needed - remaining_qty

                else:
                    current_stock = Stock.objects.filter(product=item.product, warehouse=warehouse).aggregate(total=Sum('quantity'))['total'] or 0
                    
                    if current_stock >= qty_needed:
                        take_qty = qty_needed
                    else:
                        take_qty = current_stock 
                    
                    if take_qty > 0:
                        shipment_cost_accumulated += (take_qty * item.product.cost_price)

                        StockService.change_stock(
                            product=item.product,
                            warehouse=warehouse,
                            quantity_change=-take_qty,
                            transaction_type='sale',
                            user=user,
                            content_object=sales_order,
                            notes=f"Shipped via Shipment #{shipment.id}"
                        )
                    fulfilled_now = take_qty

                if fulfilled_now > 0:

                    total_shipment_cogs += shipment_cost_accumulated

                    current_total_cost = item.quantity_fulfilled * item.cost_price
                    new_total_cost = current_total_cost + shipment_cost_accumulated
                    new_total_qty = item.quantity_fulfilled + fulfilled_now
                    
                    if new_total_qty > 0:
                        item.cost_price = new_total_cost / new_total_qty
                    
                    item.quantity_fulfilled += fulfilled_now
                    item.save()
                    items_shipped_count += 1

            if items_shipped_count == 0:
                raise ValidationError("No items could be fulfilled (Insufficient Stock).")

            all_fulfilled = True
            partially_fulfilled = False
            
            for item in sales_order.items.all():
                if item.quantity_fulfilled < item.quantity:
                    all_fulfilled = False
                if item.quantity_fulfilled > 0:
                    partially_fulfilled = True
            
            if all_fulfilled:
                sales_order.status = 'out_for_delivery'
            elif partially_fulfilled:
                sales_order.status = 'partially_delivered'
            
            sales_order.save()

            if total_shipment_cogs > 0:
                settings_obj = FinanceSettings.objects.first()
                if settings_obj and settings_obj.default_cogs_account and settings_obj.default_inventory_account:
                    
                    je = JournalEntry.objects.create(
                        date=timezone.now().date(),
                        description=f"COGS for Shipment #{shipment.id} (SO-{sales_order.sales_order_number})",
                        status='Posted',
                        created_by=user,
                        warehouse=warehouse,
                        content_object=shipment
                    )

                    JournalEntryItem.objects.create(
                        journal_entry=je,
                        account=settings_obj.default_cogs_account,
                        debit=total_shipment_cogs,
                        credit=0,
                        description=f"Cost of sales for SO-{sales_order.sales_order_number}"
                    )

                    JournalEntryItem.objects.create(
                        journal_entry=je,
                        account=settings_obj.default_inventory_account,
                        debit=0,
                        credit=total_shipment_cogs,
                        description=f"Inventory reduction for Shipment #{shipment.id}"
                    )
            
        return shipment


    @staticmethod
    def create_sales_order_transaction(user, warehouse, order_data, items_data):

        with transaction.atomic():
            valid_fields = {f.name for f in SalesOrder._meta.get_fields()}
            model_data = {k: v for k, v in order_data.items() if k in valid_fields}

            amount_received = Decimal(order_data.get('amount_received', 0) or 0)
            payment_method_obj = order_data.get('payment_method_obj', None)

            sales_order = SalesOrder(**model_data)
            sales_order.user = user
            sales_order.warehouse = warehouse

            if sales_order.status == 'draft':
                 sales_order.status = 'confirmed'
            
            sales_order.save()

            subtotal = Decimal('0.00')
            for item_data in items_data:
                if not item_data: continue
                
                item_data.pop('sales_order', None)
                item_data.pop('DELETE', None)

                sales_order_item = SalesOrderItem(sales_order=sales_order, **item_data)
                if sales_order_item.product:
                    sales_order_item.cost_price = sales_order_item.product.cost_price
                sales_order_item.save()
                subtotal += sales_order_item.subtotal

            discount_val = Decimal(order_data.get('discount', 0) or 0)
            tax_amount = Decimal(order_data.get('tax_amount', 0) or 0) # নতুন ফিল্ড সাপোর্ট
            round_off = Decimal(order_data.get('round_off_amount', 0) or 0)
            
            sales_order.discount = discount_val
            sales_order.tax_amount = tax_amount
            sales_order.round_off_amount = round_off
            sales_order.total_amount = (subtotal - discount_val) + tax_amount - round_off
            sales_order.save()

            if amount_received > 0:
                if amount_received >= sales_order.total_amount:
                    sales_order.payment_status = 'paid'
                else:
                    sales_order.payment_status = 'partial'
                sales_order.save()

                if payment_method_obj:
                    SalesPayment.objects.create(
                        sales_order=sales_order,
                        payment_method=payment_method_obj,
                        amount=amount_received,
                        recorded_by=user
                    )

            SalesService._create_invoice_journal(sales_order, user)
            
            if amount_received > 0 and payment_method_obj:
                 payment_obj = sales_order.payments.last()
                 if payment_obj:
                     SalesService._create_payment_journal(sales_order, payment_obj, user)

            return sales_order


    @staticmethod
    def _create_invoice_journal(sales_order, user):
        settings_obj = FinanceSettings.objects.first()
        if not settings_obj: return

        ar_account = settings_obj.default_ar_account
        sales_account = settings_obj.default_sales_revenue_account

        tax_account = settings_obj.default_tax_payable_account
        shipping_account = settings_obj.default_shipping_income_account

        if ar_account and sales_account:
            journal = JournalEntry.objects.create(
                date=sales_order.order_date.date(),
                description=f"Invoice for SO-{sales_order.pk}",
                created_by=user,
                content_object=sales_order,
                warehouse=sales_order.warehouse,
                status='Posted'
            )

            JournalEntryItem.objects.create(
                journal_entry=journal, 
                account=ar_account, 
                debit=sales_order.total_amount, 
                credit=0
            )

            items_total = sum(item.subtotal for item in sales_order.items.all())
            net_revenue = items_total - sales_order.discount
            
            JournalEntryItem.objects.create(
                journal_entry=journal, 
                account=sales_account, 
                debit=0, 
                credit=net_revenue
            )

            if sales_order.tax_amount > 0 and tax_account:
                JournalEntryItem.objects.create(
                    journal_entry=journal, 
                    account=tax_account, 
                    debit=0, 
                    credit=sales_order.tax_amount
                )
                

            if sales_order.shipping_cost > 0 and shipping_account:
                 JournalEntryItem.objects.create(
                    journal_entry=journal, 
                    account=shipping_account, 
                    debit=0, 
                    credit=sales_order.shipping_cost
                )

            journal.total_debit = sales_order.total_amount
            journal.total_credit = sales_order.total_amount
            journal.save()

    @staticmethod
    def _create_payment_journal(sales_order, payment, user):
        settings_obj = FinanceSettings.objects.first()
        if not settings_obj: return
        
        ar_account = settings_obj.default_ar_account
        debit_account = payment.payment_method.chart_of_account if payment.payment_method else None

        if ar_account and debit_account:
            journal = JournalEntry.objects.create(
                date=payment.payment_date.date(),
                description=f"Payment for SO-{sales_order.sales_order_number}",
                created_by=user,
                content_object=sales_order,
                warehouse=sales_order.warehouse,
                status='Posted'
            )
            
            JournalEntryItem.objects.create(journal_entry=journal, account=debit_account, debit=payment.amount, credit=0)
            JournalEntryItem.objects.create(journal_entry=journal, account=ar_account, debit=0, credit=payment.amount)
            
            journal.total_debit = payment.amount
            journal.total_credit = payment.amount
            journal.save()


    @staticmethod
    def process_sales_return(sales_return, user):
        with transaction.atomic():
            warehouse = sales_return.warehouse
            for return_item in sales_return.items.all():
                original_so_item = None
                if sales_return.sales_order:
                    original_so_item = sales_return.sales_order.items.filter(product=return_item.product).first()
                    
                allocated_lot = None
                if original_so_item:
                    allocation = original_so_item.allocations.filter(lot__isnull=False).last()
                    if allocation: allocated_lot = allocation.lot
                    
                StockService.change_stock(
                    product=return_item.product,
                    warehouse=warehouse,
                    quantity_change=return_item.quantity,
                    transaction_type='return_in',
                    user=user,
                    content_object=sales_return,
                    location=allocated_lot.location if allocated_lot else None,
                    lot_serial=allocated_lot,
                    notes=f"Returned from SO-{sales_return.sales_order.sales_order_number if sales_return.sales_order else 'Unknown'}"
                )
                    
                if allocated_lot:
                    return_item.lot_sold_from = allocated_lot
                    return_item.save()
            
            if sales_return.sales_order:
                 sales_return.sales_order.status = 'returned'
                 sales_return.sales_order.save()
                 
            return sales_return