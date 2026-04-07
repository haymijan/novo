# sales/signals.py

from django.db.models.signals import post_save
from django.dispatch import receiver
from decimal import Decimal

from .models import SalesOrder, SalesReturnItem, SalesPayment
from finance.ar.models import CustomerInvoice
from finance.gl.services import create_journal_entry
from finance.gl.models import FinanceSettings, CustomerRefund

from finance.banking.models import BankTransaction, BankAccount
from finance.cash.models import CashTransaction, CashRegister

#========================================================

@receiver(post_save, sender=SalesOrder)
def create_financial_entries_on_sale_delivery(sender, instance, created, **kwargs):

    if getattr(instance, 'skip_stock_update', False):
        return

    if instance.notes and "POS Sale #" in instance.notes:
        return

    if not created and instance.status in ['delivered', 'partially_delivered'] and kwargs.get('update_fields') and 'status' in kwargs['update_fields']:
        
        finance_settings = FinanceSettings.objects.first()
        if not finance_settings:
            print("Finance settings not found!")
            return

        revenue_account = finance_settings.default_sales_revenue_account
        ar_account = finance_settings.default_ar_account
        cogs_account = finance_settings.default_cogs_account
        inventory_account = finance_settings.default_inventory_account

        if not (revenue_account and ar_account and cogs_account and inventory_account):
            print("One or more default accounts are missing in Finance Settings.")
            return

        invoice_total = instance.total_amount 

        invoice, invoice_created = CustomerInvoice.objects.get_or_create(
            sales_order=instance,
            defaults={
                'customer': instance.customer,
                'invoice_date': instance.order_date,
                'due_date': instance.order_date,
                'total_amount': invoice_total,
                'status': 'Submitted',
                'created_by': instance.user,
                'revenue_account': revenue_account
            }
        )
        
        if not invoice_created:
            invoice.total_amount = invoice_total
            invoice.save(update_fields=['total_amount'])
            # [FIXED] 'return' removed so execution continues below

        # [FIX: Double Booking Solved] 
        # Revenue Journal is removed from here because it's handled in confirm_sales_order service.

        total_cost_price = instance.get_total_cost_price()
        if total_cost_price > 0:
            create_journal_entry(
                date=instance.order_date.date(),
                description=f"Cost of goods sold for SO #{instance.id}",
                debit_account=cogs_account,
                credit_account=inventory_account,
                amount=total_cost_price,
                user=instance.user,
                warehouse=instance.warehouse,
                content_object=instance
            )

@receiver(post_save, sender=SalesReturnItem)
def create_cogs_reversal_on_return_item(sender, instance, created, **kwargs):

    if created:
        finance_settings = FinanceSettings.objects.first()
        if not finance_settings:
            return

        cogs_account = finance_settings.default_cogs_account
        inventory_account = finance_settings.default_inventory_account

        if not (cogs_account and inventory_account):
            return

        cost_price = Decimal('0.00')
        if instance.lot_sold_from:
            cost_price = instance.lot_sold_from.cost_price
        elif instance.product:
            cost_price = instance.product.cost_price
        
        total_cost_value = cost_price * instance.quantity
        
        if total_cost_value > 0:
            sales_return = instance.sales_return
            sales_order_id = sales_return.sales_order.id if sales_return.sales_order else "N/A"

            create_journal_entry(
                date=sales_return.return_date.date(),
                description=f"Reverse COGS for Return #{sales_return.id} (Ref: SO-{sales_order_id})",
                debit_account=inventory_account,
                credit_account=cogs_account,
                amount=total_cost_value,
                user=sales_return.user,
                warehouse=sales_return.warehouse,
                content_object=instance
            )

@receiver(post_save, sender=SalesPayment)
def create_transaction_on_sales_payment(sender, instance, created, **kwargs):

    if created:
        payment = instance
        method = payment.payment_method
        sales_order = payment.sales_order

        payment_user = getattr(payment, 'user', None)
        if not payment_user:
            payment_user = getattr(payment, 'recorded_by', None)
        if not payment_user:
            payment_user = getattr(payment, 'created_by', None)

        if method and method.type in ['Bank', 'Bank/Card', 'Mobile']:
            bank_account = None
            if method.chart_of_account:
                bank_account = BankAccount.objects.filter(chart_of_account=method.chart_of_account).first()

            if bank_account:
                BankTransaction.objects.create(
                    bank_account=bank_account,
                    transaction_date=payment.payment_date,
                    transaction_type='deposit',
                    amount=payment.amount,
                    description=f"Payment received for SO-{sales_order.sales_order_number or sales_order.id}",
                    reference_number=payment.reference or str(payment.id),
                    created_by=payment_user,
                    reconciliation_status='unreconciled'
                )

                bank_account.current_balance += payment.amount
                bank_account.save(update_fields=['current_balance'])

        elif method and method.type == 'Cash':
            cash_register = None
            if method.chart_of_account:
                cash_register = CashRegister.objects.filter(chart_of_account=method.chart_of_account).first()

            if not cash_register and sales_order.warehouse:
                cash_register = CashRegister.objects.filter(warehouse=sales_order.warehouse).first()

            if cash_register:
                ref_text = payment.reference or str(payment.id)
                
                CashTransaction.objects.create(
                    register=cash_register,
                    transaction_date=payment.payment_date,
                    transaction_type='cash_in',
                    amount=payment.amount,
                    description=f"Payment received for SO-{sales_order.sales_order_number or sales_order.id} (Ref: {ref_text})",
                    created_by=payment_user
                )

                cash_register.current_balance += payment.amount
                cash_register.save(update_fields=['current_balance'])

@receiver(post_save, sender=SalesOrder)
def activate_gift_cards_on_delivery(sender, instance, created, **kwargs):
    if instance.status == 'delivered' and instance.payment_status == 'paid':
        for item in instance.items.all():
            if item.issued_gift_card:
                card = item.issued_gift_card
                if not card.is_active:
                    card.is_active = True
                    card.current_balance = item.unit_price
                    card.save()
                    GiftCardTransaction.objects.create(
                        gift_card=card,
                        amount=card.current_balance,
                        transaction_type='activation',
                        reference=f"SO-{instance.id}"
                    )