from django.db import transaction
from django.utils import timezone
from django.conf import settings
from django.db.models import Sum, F, DecimalField
from .models import PurchaseReturn, PurchaseReturnItem, SupplierCreditNote
from finance.gl.services import create_journal_entry
from finance.gl.models import ChartOfAccount, FinanceSettings
from decimal import Decimal

#=======================================================================

def get_finance_settings():
    settings = FinanceSettings.objects.first()
    if not settings:
        raise Exception("Finance Settings not found.")
    return settings

def create_financial_records_from_purchase_return(purchase_return: PurchaseReturn, user):
    """
    Purchase Return shipped হলে Supplier Credit Note তৈরি করে এবং
    Inventory, COGS (অথবা Purchase Return Account) এবং Accounts Payable সংক্রান্ত জার্নাল পোস্ট করে।
    """
    with transaction.atomic():
        total_return_value = purchase_return.items.aggregate(
            total=Sum(F('quantity') * F('unit_price'), output_field=DecimalField(max_digits=12, decimal_places=2))
        )['total'] or Decimal(0)

        if total_return_value > 0:

            credit_note, created = SupplierCreditNote.objects.get_or_create(
                purchase_return=purchase_return,
                defaults={
                    'supplier': purchase_return.supplier,
                    'created_date': purchase_return.return_date.date(),
                    'amount': total_return_value,
                    'amount_available': total_return_value,
                    'status': 'Available',
                    'notes': f"Credit from Purchase Return #{purchase_return.pk}",
                    'created_by': user
                }
            )
            if not created:
                 print(f"Warning: SupplierCreditNote for Purchase Return #{purchase_return.pk} already exists.")

            try:

                settings = get_finance_settings()

                inventory_account = settings.default_inventory_account
                cogs_account = settings.default_cogs_account
                ap_account = settings.default_ap_account

                if not (inventory_account and cogs_account and ap_account):
                    raise Exception("Inventory, COGS, or AP account not set in Finance Settings.")

                journal_entry_inv, error_inv = create_journal_entry(
                    date=purchase_return.return_date.date(),
                    description=f"Inventory adj. for PR #{purchase_return.pk}",
                    debit_account=cogs_account,
                    credit_account=inventory_account,
                    amount=total_return_value,
                    user=user,
                    warehouse=purchase_return.warehouse,
                    content_object=purchase_return
                )
                if error_inv:
                    raise Exception(f"Failed to create Inventory JE for purchase return: {error_inv}")

                journal_entry_ap, error_ap = create_journal_entry(
                    date=purchase_return.return_date.date(),
                    description=f"AP adj. & Credit Note trigger for PR #{purchase_return.pk}",
                    debit_account=ap_account,
                    credit_account=cogs_account,
                    amount=total_return_value,
                    user=user,
                    warehouse=purchase_return.warehouse,
                    content_object=credit_note
                )
                if error_ap:
                    raise Exception(f"Failed to create AP JE for purchase return: {error_ap}")

            except Exception as e:
                raise Exception(f"Failed during financial record creation for PR: {str(e)}")

            if purchase_return.status == 'shipped':
                purchase_return.status = 'completed'
                purchase_return.save(update_fields=['status'])

    return credit_note if 'credit_note' in locals() else None