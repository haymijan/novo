from django.db.models.signals import post_save
from django.dispatch import receiver
from django.db.models import Sum, F, Q, ExpressionWrapper, DecimalField
from django.db import models

from sales.models import SalesOrder, SalesOrderItem, SalesReturn, SalesReturnItem
from .models import JobCost

@receiver(post_save, sender=SalesOrder)
def create_or_update_job_cost_on_sale(sender, instance, created, **kwargs):
    if instance.status in ['delivered', 'partially_delivered']:
        sales_order = instance
        gross_amount = sales_order.total_amount or 0
        gift_card_liability = sales_order.items.filter(
            Q(product__product_type='gift_card') | Q(product__tracking_method='none')
        ).aggregate(
            total=Sum(F('quantity_fulfilled') * F('unit_price'), output_field=DecimalField())
        )['total'] or 0

        real_revenue = gross_amount - gift_card_liability

        material_cost_agg = sales_order.items.exclude(
            product__product_type='gift_card'
        ).aggregate(
            total_cost=Sum(
                ExpressionWrapper(
                    F('quantity_fulfilled') * F('cost_price'),
                    output_field=DecimalField()
                )
            )
        )
        total_material_cost = material_cost_agg.get('total_cost') or 0

        profit = real_revenue - total_material_cost

        JobCost.objects.update_or_create(
            sales_order=sales_order,
            defaults={
                'total_revenue': real_revenue, 
                'total_material_cost': total_material_cost,
                'profit': profit
            }
        )

@receiver(post_save, sender=SalesReturnItem)
def update_job_cost_on_return(sender, instance, created, **kwargs):

    if created: 
        returned_item = instance
        if not returned_item.sales_return or not returned_item.sales_return.sales_order:
            return

        original_order = returned_item.sales_return.sales_order

        try:
            job_cost = JobCost.objects.get(sales_order=original_order)

            returned_revenue = returned_item.quantity * returned_item.unit_price
            returned_cost = 0
            if hasattr(returned_item, 'lot_sold_from') and returned_item.lot_sold_from and returned_item.lot_sold_from.cost_price:
                 returned_cost = returned_item.quantity * returned_item.lot_sold_from.cost_price
            else:
                 returned_cost = returned_item.quantity * returned_item.product.cost_price

            job_cost.total_revenue -= returned_revenue
            job_cost.total_material_cost -= returned_cost
            job_cost.profit = job_cost.total_revenue - job_cost.total_material_cost
            job_cost.save()

        except JobCost.DoesNotExist:
            pass