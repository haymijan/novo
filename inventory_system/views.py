# inventory_system/views.py (Fixed for New Sales Architecture)

import json
from decimal import Decimal
from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.db.models import (
    Sum, Count, Q, F, Value, IntegerField, ExpressionWrapper, DecimalField,
    OuterRef, Subquery
)
from django.db.models.functions import Coalesce, TruncMonth
from django.utils import timezone
from django.urls import reverse_lazy
from datetime import timedelta, datetime
from collections import OrderedDict

# Local Application Imports
from products.models import Product
from sales.models import SalesOrder, SalesOrderItem, SalesReturn, SalesReturnItem
from partners.models import Supplier, Customer
from stock.models import Stock, LotSerialNumber
from django.contrib.auth import views as auth_views
from .forms import CustomPasswordResetForm

from django.core.cache import cache

DEFAULT_CURRENCY_SYMBOL = 'QAR '


# Helper function to get date range from request
def get_date_range(request):
    today = timezone.now().date()
    start_date_str = request.GET.get('start_date')
    end_date_str = request.GET.get('end_date')
    period = request.GET.get('period', 'today')

    query_start_date, query_end_date = None, None
    form_start_date, form_end_date = None, None

    if period:
        if period == 'today':
            query_start_date = query_end_date = today
        elif period == 'week':
            query_start_date = today - timedelta(days=today.weekday())
            query_end_date = today
        elif period == 'month':
            query_start_date = today.replace(day=1)
            query_end_date = today
    
    if start_date_str and end_date_str:
        try:
            query_start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
            query_end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
            form_start_date, form_end_date = query_start_date, query_end_date
            period = None
        except (ValueError, TypeError):
            query_start_date = query_end_date = today
            period = 'today'
            
    if not query_start_date:
        query_start_date = query_end_date = today

    end_date_for_filtering = query_end_date + timedelta(days=1)

    return {
        'query_start_date': query_start_date,
        'query_end_date': query_end_date,
        'end_date_for_filtering': end_date_for_filtering,
        'form_start_date': form_start_date,
        'form_end_date': form_end_date,
        'period': period
    }

def get_purchase_suggestions_queryset(user, user_warehouse):
    """
    এই ফাংশনটি প্রতিটি ব্রাঞ্চের জন্য আলাদাভাবে পারচেজ সাজেশন তৈরি করে।
    """
    thirty_days_ago = timezone.now().date() - timedelta(days=30)

    stock_qs = Stock.objects.values(
        'product__id', 
        'warehouse__id',
        'product__name',
        'product__product_code'
    ).annotate(
        current_stock=Sum('quantity')
    ).order_by('product__name')

    if not user.is_superuser and user_warehouse:
        stock_qs = stock_qs.filter(warehouse=user_warehouse)

    sold_sq = SalesOrderItem.objects.filter(
        product_id=OuterRef('product__id'),
        sales_order__warehouse_id=OuterRef('warehouse__id'),
        sales_order__order_date__gte=thirty_days_ago
    ).values('product_id').annotate(total=Sum('quantity')).values('total')

    returned_sq = SalesReturnItem.objects.filter(
        product_id=OuterRef('product__id'),
        sales_return__warehouse_id=OuterRef('warehouse__id'),
        sales_return__return_date__gte=thirty_days_ago
    ).values('product_id').annotate(total=Sum('quantity')).values('total')

    suggestions = stock_qs.annotate(
        total_sold=Coalesce(Subquery(sold_sq, output_field=DecimalField()), Decimal(0)),
        total_returned=Coalesce(Subquery(returned_sq, output_field=DecimalField()), Decimal(0))
    ).annotate(
        net_sales_30_days=F('total_sold') - F('total_returned')
    ).filter(
        current_stock__lt=F('net_sales_30_days')
    )

    return suggestions

@login_required
def dashboard(request):
    user = request.user
    user_warehouse = getattr(user, 'warehouse', None)

    # POS Staff চেক
    if user.groups.filter(name='POS Sales Staff').exists():
        return redirect('pos:pos_view')

    # ==========================================
    # 1. CACHE KEY GENERATION
    # ==========================================
    period = request.GET.get('period', 'today')
    start_str = request.GET.get('start_date', '')
    end_str = request.GET.get('end_date', '')
    warehouse_id = user_warehouse.id if user_warehouse else 'global'
    
    cache_key = f"dashboard_stats_{user.id}_{warehouse_id}_{period}_{start_str}_{end_str}"

    # 2. TRY TO GET DATA FROM CACHE
    context = cache.get(cache_key)

    # 3. IF DATA NOT IN CACHE, CALCULATE EVERYTHING
    if not context:
        date_info = get_date_range(request)
        today = timezone.now().date()

        sales_filtered_qs = SalesOrder.objects.filter(
            status='delivered', 
            order_date__gte=date_info['query_start_date'], 
            order_date__lt=date_info['end_date_for_filtering']
        )
        returns_filtered_qs = SalesReturn.objects.filter(
            return_date__gte=date_info['query_start_date'], 
            return_date__lt=date_info['end_date_for_filtering']
        )
        
        if not user.is_superuser and user_warehouse:
            sales_filtered_qs = sales_filtered_qs.filter(warehouse=user_warehouse)
            returns_filtered_qs = returns_filtered_qs.filter(warehouse=user_warehouse)

        # --- START: Total Profit Calculation (FIXED) ---
        total_profit = Decimal('0.0')
        if user.is_superuser:
            # 1. Gross Profit from Sales
            # FIX: Removed 'lot_sold_from' and used 'cost_price'
            sales_items = SalesOrderItem.objects.filter(sales_order__in=sales_filtered_qs)
            gross_profit = sales_items.aggregate(
                total_profit=Sum(
                    F('quantity_fulfilled') * (F('unit_price') - F('cost_price')), 
                    output_field=DecimalField()
                )
            )['total_profit'] or Decimal('0.0')
            
            # 2. Lost Profit from Returns
            # Note: SalesReturnItem still has 'lot_sold_from' so this is fine, 
            # but we use 'unit_price' - 'lot_sold_from__cost_price' if available.
            returned_items = SalesReturnItem.objects.filter(sales_return__in=returns_filtered_qs).select_related('product', 'lot_sold_from')
            lost_profit = returned_items.aggregate(
                lost_profit=Sum(
                    F('quantity') * (F('unit_price') - Coalesce(F('lot_sold_from__cost_price'), F('product__cost_price'))), 
                    output_field=DecimalField()
                )
            )['lost_profit'] or Decimal('0.0')
            
            total_profit = gross_profit - lost_profit
        # --- END: Total Profit Calculation ---

        # --- START: Inventory Turnover & Avg Days to Sell Calculation ---
        inventory_turnover_ratio = 0.0
        avg_days_to_sell = 0.0

        # 1. Calculate COGS
        # FIX: Removed 'lot_sold_from' and used 'cost_price'
        cogs_sales_qs = SalesOrderItem.objects.filter(sales_order__in=sales_filtered_qs)
        cogs_returns_qs = SalesReturnItem.objects.filter(sales_return__in=returns_filtered_qs).select_related('lot_sold_from')

        total_cogs_sales = cogs_sales_qs.aggregate(
            total=Sum(F('quantity_fulfilled') * F('cost_price'), output_field=DecimalField())
        )['total'] or Decimal('0.0')
        
        total_cogs_returns = cogs_returns_qs.aggregate(
            total=Sum(F('quantity') * Coalesce(F('lot_sold_from__cost_price'), F('product__cost_price')), output_field=DecimalField())
        )['total'] or Decimal('0.0')

        period_cogs = total_cogs_sales - total_cogs_returns

        # 2. Calculate Current Total Inventory Value
        inventory_value_qs = LotSerialNumber.objects.filter(quantity__gt=0)
        if not user.is_superuser and user_warehouse:
            inventory_value_qs = inventory_value_qs.filter(location__warehouse=user_warehouse)
        
        total_inventory_value = inventory_value_qs.aggregate(
            total_value=Sum(F('quantity') * F('cost_price'), output_field=DecimalField())
        )['total_value'] or Decimal('0.0')

        # 3. Calculate Ratios
        num_days_in_period = (date_info['query_end_date'] - date_info['query_start_date']).days + 1
        
        if period_cogs > 0 and total_inventory_value > 0 and num_days_in_period > 0:
            avg_inventory_proxy = total_inventory_value 
            period_turnover = period_cogs / avg_inventory_proxy
            annualization_factor = 365.0 / num_days_in_period
            inventory_turnover_ratio = float(period_turnover * Decimal(annualization_factor))
            
            if inventory_turnover_ratio > 0:
                avg_days_to_sell = 365.0 / inventory_turnover_ratio
        # --- END: Inventory Turnover Calculation ---

        stock_qs_user_specific = Stock.objects.all()
        if not user.is_superuser and user_warehouse:
            stock_qs_user_specific = stock_qs_user_specific.filter(warehouse=user_warehouse)
        
        start_of_month = today.replace(day=1)
        sales_today_qs = SalesOrder.objects.filter(status='delivered', order_date__date=today)
        returns_today_qs = SalesReturn.objects.filter(return_date__date=today)
        sales_month_qs = SalesOrder.objects.filter(status='delivered', order_date__gte=start_of_month)
        returns_month_qs = SalesReturn.objects.filter(return_date__gte=start_of_month)
        
        if not user.is_superuser and user_warehouse:
            sales_today_qs = sales_today_qs.filter(warehouse=user_warehouse)
            returns_today_qs = returns_today_qs.filter(warehouse=user_warehouse)
            sales_month_qs = sales_month_qs.filter(warehouse=user_warehouse)
            returns_month_qs = returns_month_qs.filter(warehouse=user_warehouse)

        todays_gross_sales = sales_today_qs.aggregate(total=Sum('total_amount'))['total'] or 0
        todays_returns_total = returns_today_qs.aggregate(total=Coalesce(Sum(F('items__quantity') * F('items__unit_price')), Decimal('0.0')))['total']
        this_months_gross_sales = sales_month_qs.aggregate(total=Sum('total_amount'))['total'] or 0
        this_months_returns_total = returns_month_qs.aggregate(total=Coalesce(Sum(F('items__quantity') * F('items__unit_price')), Decimal('0.0')))['total']

        unfulfilled_orders_query = SalesOrder.objects.filter(Q(status='confirmed') | Q(status__iexact='partially_delivered'))
        if not user.is_superuser and user_warehouse:
            unfulfilled_orders_query = unfulfilled_orders_query.filter(warehouse=user_warehouse)
        unfulfilled_orders_count = unfulfilled_orders_query.count()

        expiring_lots_qs = LotSerialNumber.objects.filter(expiration_date__isnull=False, expiration_date__range=(today, today + timedelta(days=30)), quantity__gt=0)
        if not user.is_superuser and user_warehouse:
            expiring_lots_qs = expiring_lots_qs.filter(location__warehouse=user_warehouse)
        expiring_lots_count = expiring_lots_qs.count()

        sold_product_ids = SalesOrderItem.objects.filter(sales_order__order_date__gte=today - timedelta(days=90)).values_list('product_id', flat=True).distinct()
        dead_stock_count = stock_qs_user_specific.filter(quantity__gt=0).exclude(product_id__in=sold_product_ids).values('product_id').distinct().count()

        purchase_suggestion_count = get_purchase_suggestions_queryset(user, user_warehouse).count()

        twelve_months_ago = (today - timedelta(days=365)).replace(day=1)
        chart_sales_base_qs = SalesOrder.objects.filter(status='delivered', order_date__gte=twelve_months_ago)
        chart_returns_base_qs = SalesReturn.objects.filter(return_date__gte=twelve_months_ago)

        if not user.is_superuser and user_warehouse:
            chart_sales_base_qs = chart_sales_base_qs.filter(warehouse=user_warehouse)
            chart_returns_base_qs = chart_returns_base_qs.filter(warehouse=user_warehouse)

        monthly_sales_query = chart_sales_base_qs.annotate(month=TruncMonth('order_date')).values('month').annotate(total=Sum('total_amount')).order_by('month')
        monthly_returns_query = chart_returns_base_qs.annotate(month=TruncMonth('return_date')).values('month').annotate(total=Sum(F('items__quantity') * F('items__unit_price'))).order_by('month')
        monthly_orders_query = chart_sales_base_qs.annotate(month=TruncMonth('created_at')).values('month').annotate(order_count=Count('id')).order_by('month')

        months_data = OrderedDict()
        current_month = twelve_months_ago
        while current_month <= today.replace(day=1):
            months_data[current_month.strftime('%b %Y')] = {'sales': 0, 'returns': 0, 'orders': 0}
            next_month = (current_month.replace(day=28) + timedelta(days=4))
            current_month = next_month.replace(day=1)

        for data in monthly_sales_query:
            key = data['month'].strftime('%b %Y')
            if key in months_data: months_data[key]['sales'] = float(data['total'] or 0)
        for data in monthly_returns_query:
            key = data['month'].strftime('%b %Y')
            if key in months_data: months_data[key]['returns'] = float(data['total'] or 0)
        for data in monthly_orders_query:
            key = data['month'].strftime('%b %Y')
            if key in months_data: months_data[key]['orders'] = int(data['order_count'] or 0)

        products_with_stock = Product.objects.filter(stocks__isnull=False).distinct()
        if not user.is_superuser and user_warehouse:
            products_with_stock = products_with_stock.filter(stocks__warehouse=user_warehouse)
        
        stock_aggregation = products_with_stock.annotate(
            total_quantity=Sum('stocks__quantity', filter=Q(stocks__warehouse=user_warehouse) if not user.is_superuser and user_warehouse else Q())
        ).aggregate(
            in_stock_count=Count('pk', filter=Q(total_quantity__gt=F('min_stock_level'))),
            low_stock_count=Count('pk', filter=Q(total_quantity__lte=F('min_stock_level'), total_quantity__gt=0)),
            out_of_stock_count=Count('pk', filter=Q(total_quantity__lte=0)),
        )
        
        category_data_query = products_with_stock.values('category__name').annotate(count=Count('id')).order_by('-count')

        # CONTEXT তৈরি করা (সব ডাটা এখানে আসবে)
        context = {
            'period': date_info['period'],
            'start_date': date_info['form_start_date'],
            'end_date': date_info['form_end_date'],
            
            'todays_net_sales': todays_gross_sales - todays_returns_total,
            'todays_gross_sales': todays_gross_sales,
            'todays_returns_total': todays_returns_total,
            'this_months_net_sales': this_months_gross_sales - this_months_returns_total,
            'this_months_gross_sales': this_months_gross_sales,
            'this_months_returns_total': this_months_returns_total,

            'total_profit': total_profit,
            'inventory_turnover_ratio': inventory_turnover_ratio,
            'avg_days_to_sell': avg_days_to_sell,

            'purchase_suggestion_count': purchase_suggestion_count,
            'dead_stock_count': dead_stock_count,
            'expiring_lots_count': expiring_lots_count,
            'unfulfilled_orders_count': unfulfilled_orders_count,

            'total_products': products_with_stock.count(),
            'in_stock_products': stock_aggregation.get('in_stock_count', 0),
            'low_stock_products_count': stock_aggregation.get('low_stock_count', 0),
            'out_of_stock_products': stock_aggregation.get('out_of_stock_count', 0),
            'total_customers': Customer.objects.count(),
            'total_suppliers': Supplier.objects.count(),

            'category_labels': json.dumps([item['category__name'] or "Uncategorized" for item in category_data_query]),
            'category_data': json.dumps([item['count'] for item in category_data_query]),
            'status_labels': json.dumps(['In Stock', 'Low Stock', 'Out of Stock']),
            'status_data': json.dumps([
                stock_aggregation.get('in_stock_count', 0),
                stock_aggregation.get('low_stock_count', 0),
                stock_aggregation.get('out_of_stock_count', 0)
            ]),

            'monthly_sales_labels': json.dumps(list(months_data.keys())),
            'monthly_sales_data': json.dumps([d['sales'] for d in months_data.values()]),
            'monthly_returns_data': json.dumps([d['returns'] for d in months_data.values()]),
            'monthly_orders_labels': json.dumps(list(months_data.keys())),
            'monthly_orders_data': json.dumps([d['orders'] for d in months_data.values()]),
            
            'DEFAULT_CURRENCY_SYMBOL': DEFAULT_CURRENCY_SYMBOL,
            'title': 'Dashboard'
        }
        
        # 4. SAVE DATA TO CACHE
        cache.set(cache_key, context, 300)

    return render(request, 'dashboard.html', context)


@login_required
def home(request):
    return redirect('dashboard')

class CustomPasswordResetView(auth_views.PasswordResetView):
    form_class = CustomPasswordResetForm
    template_name = 'registration/password_reset_form.html'
    success_url = reverse_lazy('password_reset_done')

    def post(self, request, *args, **kwargs):
        form = self.get_form()
        if form.is_valid():
            return self.form_valid(form)
        else:
            return self.form_invalid(form)