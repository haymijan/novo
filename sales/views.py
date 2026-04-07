# sales/views.py

from django.shortcuts import render, redirect, get_object_or_404
from django.http import HttpResponse, JsonResponse
from django.contrib.auth.decorators import login_required, permission_required
from django.db import transaction
from django.db.models import Sum, Q, F, Count
from django.core.paginator import Paginator
from django.contrib import messages
from django.forms import formset_factory, inlineformset_factory
from datetime import timedelta
import json
from io import BytesIO
import os
from django.conf import settings
from openpyxl import Workbook
from openpyxl.styles import Font

from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image, PageBreak
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import inch, mm
from reportlab.lib.enums import TA_CENTER, TA_RIGHT, TA_LEFT
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from reportlab.pdfgen import canvas

from .forms import SalesOrderFilterForm
from .models import SalesOrder, SalesOrderItem, SalesReturn, SalesReturnItem
from stock.models import InventoryTransaction, LotSerialNumber, Location, Stock
from .forms import (
    SalesOrderForm,
    SalesOrderItemFormSet,
    SalesOrderItemFulfillmentForm,
    SalesOrderItemFulfillmentFormSet,
    FindSalesOrderForm,
    SalesReturnForm,
    SalesReturnItemFormSet,
    SalesReturnItemForm,
    SalesOrderItemFulfillmentForm
)
from products.models import Product
from partners.forms import CustomerForm
from partners.models import Customer
from stock.forms import DateRangeForm
from stock.services import StockService
from .services import SalesService
from finance.ar.services import create_financial_records_from_so
from finance.ar.services import create_credit_note_for_return
from decimal import Decimal
from django.core.exceptions import ValidationError
from finance.gl.models import CustomerRefund

from marketing.models import Coupon
from django.utils import timezone

from marketing.models import GiftCard
from finance.gl.models import JournalEntry, JournalEntryItem, FinanceSettings
from finance.banking.models import PaymentMethod
from stock.models import Stock, InventoryTransaction, LotSerialNumber


#===================================================================================

DEFAULT_CURRENCY_SYMBOL = 'QAR '

class NumberedCanvas(canvas.Canvas):
    def __init__(self, *args, **kwargs):
        canvas.Canvas.__init__(self, *args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_page_number(num_pages)
            canvas.Canvas.showPage(self)

    def draw_page_number(self, page_count):
        self.setFont("Helvetica", 9)
        self.drawRightString(200*mm, 20*mm, f"Page {self._pageNumber} of {page_count}")

def add_page_number(canvas, doc):
    page_num = canvas.getPageNumber()
    text = f"Page {page_num}"
    canvas.drawString(doc.leftMargin, inch / 2, text)


def apply_sales_order_filters(queryset, request):
    form = DateRangeForm(request.GET or None)
    if form.is_valid():
        start_date = form.cleaned_data.get('start_date')
        end_date = form.cleaned_data.get('end_date')
        status = request.GET.get('status')
        order_number = request.GET.get('order_number')

        if start_date:
            queryset = queryset.filter(created_at__date__gte=start_date)
        if end_date:
            end_date_inclusive = end_date + timedelta(days=1)
            queryset = queryset.filter(created_at__date__lt=end_date_inclusive)
        if status:
            queryset = queryset.filter(status=status)
        if order_number:
            queryset = queryset.filter(pk=order_number)
    return queryset, form

@login_required
@permission_required('sales.view_salesorder', login_url='/admin/')
def sales_order_list(request):
    sales_orders_list = SalesOrder.objects.select_related('customer', 'user', 'warehouse').order_by('-created_at')
    
    user = request.user
    if not user.is_superuser:
        user_warehouse = getattr(user, 'warehouse', None)
        if user_warehouse:
            sales_orders_list = sales_orders_list.filter(warehouse=user_warehouse)
    
    filter_param = request.GET.get('filter')
    if filter_param == 'unfulfilled':
        sales_orders_list = sales_orders_list.filter(Q(status='confirmed') | Q(status='processing'))

    form = SalesOrderFilterForm(request.GET, user=user) 
    if form.is_valid():
        start_date = form.cleaned_data.get('start_date')
        end_date = form.cleaned_data.get('end_date')
        order_number = form.cleaned_data.get('order_number')
        selected_user = form.cleaned_data.get('user')
        warehouse = form.cleaned_data.get('warehouse')

        if start_date:
            sales_orders_list = sales_orders_list.filter(created_at__date__gte=start_date)
        if end_date:
            sales_orders_list = sales_orders_list.filter(created_at__date__lte=end_date)
        if order_number and order_number.isdigit(): # অর্ডার নম্বর চেক করা হলো যাতে int error না দেয়
            sales_orders_list = sales_orders_list.filter(pk=order_number)
        if selected_user:
            sales_orders_list = sales_orders_list.filter(user=selected_user)
        if warehouse and user.is_superuser:
            sales_orders_list = sales_orders_list.filter(warehouse=warehouse)
    
    paginator = Paginator(sales_orders_list, 15)
    page_number = request.GET.get('page')
    sales_orders = paginator.get_page(page_number)

    context = {
        'title': 'Sales Orders',
        'sales_orders': sales_orders,
        'form': form,
    }
    return render(request, 'sales/sales_order_list.html', context)

@login_required
@permission_required('sales.view_salesorder', login_url='/admin/')
def sales_order_detail(request, pk):
    sales_order = get_object_or_404(
        SalesOrder.objects.prefetch_related('items__product', 'returns', 'payments', 'shipments'), 
        pk=pk
    )

    associated_returns = sales_order.returns.all()

    payment_methods = PaymentMethod.objects.filter(is_active=True, is_available_for_sales=True)

    context = {
        'title': f'Sales Order #{sales_order.sales_order_number or sales_order.pk}',
        'sales_order': sales_order,
        'associated_returns': associated_returns,
        'payment_methods': payment_methods,
        'DEFAULT_CURRENCY_SYMBOL': DEFAULT_CURRENCY_SYMBOL,
    }
    return render(request, 'sales/sales_order_detail.html', context)

@login_required
@permission_required('sales.add_salesorder', login_url='/admin/')
def create_sales_order(request):
    user_warehouse = getattr(request.user, 'warehouse', None)

    sales_order_form = SalesOrderForm(
        request.POST or None, 
        user=request.user, 
        initial={'status': 'draft'} 
    ) 
    
    item_formset = SalesOrderItemFormSet(
        request.POST or None, prefix='items',
        form_kwargs={'user': request.user, 'warehouse': user_warehouse}
    )

    if request.method == 'POST':
        if sales_order_form.is_valid() and item_formset.is_valid():
            try:
                order_data = sales_order_form.cleaned_data
                
                items_data = [
                    f.cleaned_data for f in item_formset 
                    if f.cleaned_data and not f.cleaned_data.get('DELETE', False)
                ]

                sales_order = SalesService.create_draft_order(
                    user=request.user,
                    warehouse=user_warehouse,
                    order_data=order_data,
                    items_data=items_data
                )

                messages.success(request, f"Sales Order #{sales_order.sales_order_number} created as DRAFT. Please confirm to proceed.")
                return redirect('sales:sales_order_detail', pk=sales_order.pk)
            
            except ValidationError as e:
                if hasattr(e, 'message'):
                    sales_order_form.add_error(None, e.message)
                else:
                    sales_order_form.add_error(None, str(e))
                messages.error(request, f"Validation Error: {e}")
            except Exception as e:
                sales_order_form.add_error(None, f"System Error: {str(e)}")
                messages.error(request, f"System Error: {str(e)}")
                print(f"SYSTEM ERROR: {e}")
        
        else:
            print("Sales Order Form Errors:", sales_order_form.errors)
            print("Item Formset Errors:", item_formset.errors)
            messages.error(request, "Please correct the errors below.")
    
    context = {
        'title': 'Create Sales Order',
        'sales_order_form': sales_order_form,
        'item_formset': item_formset,
        'customer_form': CustomerForm(),
    }
    return render(request, 'sales/create_sales_order.html', context)

@login_required
@permission_required('sales.change_salesorder', login_url='/admin/')
def confirm_sales_order(request, pk):
    try:
        SalesService.confirm_sales_order(order_id=pk, user=request.user)
        messages.success(request, "Order confirmed successfully! Invoice generated.")
    except ValidationError as e:
        messages.error(request, str(e))
    except Exception as e:
        messages.error(request, f"Error: {str(e)}")
        
    return redirect('sales:sales_order_detail', pk=pk)

@login_required
@permission_required('sales.change_salesorder', login_url='/admin/')
def add_payment_to_order(request, pk):
    if request.method == 'POST':
        try:
            amount = Decimal(request.POST.get('amount', 0))
            method_id = request.POST.get('payment_method')
            reference = request.POST.get('reference', '')
            
            if amount <= 0:
                raise ValidationError("Amount must be greater than 0")
                
            payment_method = get_object_or_404(PaymentMethod, id=method_id)
            
            SalesService.process_payment(
                order_id=pk,
                amount=amount,
                payment_method=payment_method,
                user=request.user,
                reference=reference
            )
            messages.success(request, f"Payment of {amount} recorded successfully.")
            
        except ValidationError as e:
            messages.error(request, str(e))
        except Exception as e:
            messages.error(request, f"Error processing payment: {str(e)}")
            
    return redirect('sales:sales_order_detail', pk=pk)

@login_required
@permission_required('sales.change_salesorder', login_url='/admin/')
def fulfill_sales_order(request, pk):
    sales_order = get_object_or_404(SalesOrder, pk=pk)
    
    if request.method == 'POST':
        tracking_number = request.POST.get('tracking_number', '')
        try:
            SalesService.create_shipment_and_fulfill(
                order_id=pk,
                warehouse=sales_order.warehouse,
                user=request.user,
                tracking_number=tracking_number
            )
            messages.success(request, "Order fulfilled and shipment created successfully!")
            return redirect('sales:sales_order_detail', pk=pk)
            
        except ValidationError as e:
            messages.error(request, str(e))
        except Exception as e:
            messages.error(request, f"Error: {str(e)}")

    context = {
        'sales_order': sales_order,
        'title': 'Fulfill Sales Order',
    }
    return render(request, 'sales/fulfill_sales_order.html', context)

@login_required
@permission_required('sales.change_salesorder', login_url='/admin/')
def edit_sales_order(request, pk):
    sales_order = get_object_or_404(SalesOrder, pk=pk)

    if sales_order.status != 'draft':
        messages.warning(request, "Confirmed orders cannot be edited. Please cancel and create a new one.")
        return redirect('sales:sales_order_detail', pk=pk)

    order_warehouse = sales_order.warehouse 
    sales_order_form = SalesOrderForm(request.POST or None, instance=sales_order, user=request.user)
    item_formset = SalesOrderItemFormSet(
        request.POST or None, instance=sales_order, prefix='items',
        form_kwargs={'user': request.user, 'warehouse': order_warehouse}
    )
    
    if request.method == 'POST':
        if sales_order_form.is_valid() and item_formset.is_valid():
            try:
                with transaction.atomic():
                    sales_order = sales_order_form.save()
                    items = item_formset.save(commit=False)
                    for obj in item_formset.deleted_objects:
                        obj.delete()
                        
                    total_items_amount = Decimal('0.00')
                    for item in items:
                        item.sales_order = sales_order
                        if not item.cost_price and item.product:
                            item.cost_price = item.product.cost_price
                        item.save()
                        total_items_amount += item.subtotal

                    discount = sales_order.discount or Decimal(0)
                    round_off = sales_order.round_off_amount or Decimal(0)
                    tax = sales_order.tax_amount or Decimal(0)
                    shipping = sales_order.shipping_cost or Decimal(0)
                    
                    sales_order.total_amount = total_items_amount + tax + shipping - discount - round_off
                    sales_order.save()

                messages.success(request, f"Sales Order #{sales_order.pk} updated successfully!")
                return redirect('sales:sales_order_detail', pk=sales_order.pk)

            except ValidationError as e:
                messages.error(request, e.message)
            except Exception as e:
                messages.error(request, f"An error occurred: {e}")

    context = {'title': f'Edit Sales Order #{sales_order.pk}', 'sales_order_form': sales_order_form, 'formset': item_formset}
    return render(request, 'sales/edit_sales_order.html', context)

@login_required
@permission_required('sales.delete_salesorder', login_url='/admin/')
def delete_sales_order(request, pk):
    sales_order = get_object_or_404(SalesOrder, pk=pk)
    
    if sales_order.status != 'draft':
        messages.error(request, "Only DRAFT orders can be deleted.")
        return redirect('sales:sales_order_detail', pk=pk)

    if request.method == 'POST':
        sales_order.delete()
        messages.success(request, f"Sales Order {pk} deleted successfully!")
        return redirect('sales:sales_order_list')
    context = {'sales_order': sales_order}


@login_required
def get_lots_by_location_and_product(request):
    product_id = request.GET.get('product_id')
    location_id = request.GET.get('location_id')
    if product_id and location_id:
        lots = LotSerialNumber.objects.filter(product_id=product_id, location_id=location_id, quantity__gt=0).values('id', 'lot_number', 'quantity')
        return JsonResponse(list(lots), safe=False)
    return JsonResponse([], safe=False)

@login_required
def get_product_sale_price_ajax(request):
    product_id = request.GET.get('product_id')
    if product_id:
        try:
            return JsonResponse({'sale_price': Product.objects.get(id=product_id).sale_price})
        except: pass
    return JsonResponse({}, status=400)


@login_required
@permission_required('sales.view_salesorder', raise_exception=True)
def export_sales_order_pdf(request, pk):

    sales_order = get_object_or_404(SalesOrder, pk=pk)
    
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="SO-{sales_order.pk}_{sales_order.customer.name if sales_order.customer else "Walk-in"}.pdf"'

    doc = SimpleDocTemplate(response, pagesize=A4, rightMargin=30, leftMargin=30, topMargin=30, bottomMargin=30)
    story = []

    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name='TitleStyle', fontSize=22, fontName='Helvetica-Bold', alignment=TA_RIGHT, textColor=colors.HexColor("#444444")))
    styles.add(ParagraphStyle(name='CompanyInfo', fontSize=9, fontName='Helvetica', alignment=TA_RIGHT, leading=12))
    styles.add(ParagraphStyle(name='CustomerInfo', fontSize=10, fontName='Helvetica', leading=14))
    styles.add(ParagraphStyle(name='HeaderStyle', fontSize=10, fontName='Helvetica-Bold', alignment=TA_LEFT))
    styles.add(ParagraphStyle(name='TotalHeaderStyle', fontSize=10, fontName='Helvetica-Bold', alignment=TA_RIGHT))
    styles.add(ParagraphStyle(name='SignatureStyle', fontSize=10, fontName='Helvetica', alignment=TA_CENTER))
    styles.add(ParagraphStyle(name='BoldText', fontName='Helvetica-Bold'))

    logo_path = os.path.join(settings.STATICFILES_DIRS[0], 'images', 'logo.png')
    if os.path.exists(logo_path):
        logo = Image(logo_path, width=1.8*inch, height=0.5*inch)
        header_data = [[logo, Paragraph("SALES ORDER", styles['TitleStyle'])]]
    else:
        header_data = [[Paragraph("NOVO ERP", styles['TitleStyle']), Paragraph("SALES ORDER", styles['TitleStyle'])]]

    company_info = """
    <b>NOVO ERP Solutions</b><br/>
    Doha, Qatar<br/>
    Email: info@novoerp.com<br/>
    """
    
    header_table = Table(header_data, colWidths=[4*inch, 3.5*inch], style=[('VALIGN', (0,0), (-1,-1), 'TOP')])
    story.append(header_table)
    story.append(Spacer(1, 0.1*inch))
    story.append(Paragraph(company_info, styles['CompanyInfo']))
    story.append(Spacer(1, 0.5*inch))

    customer_name = sales_order.customer.name if sales_order.customer else "Walk-in Customer"
    customer_phone = getattr(sales_order.customer, 'phone', '')
    
    customer_details = f"""
    <b>BILLED TO:</b><br/>
    {customer_name}<br/>
    {sales_order.customer.address if sales_order.customer and sales_order.customer.address else ''}<br/>
    {customer_phone}
    """
    
    order_details_data = [
        ['Order #:', f'SO-{sales_order.sales_order_number or sales_order.pk}'],
        ['Order Date:', sales_order.order_date.strftime('%d %b, %Y')],
        ['Status:', sales_order.get_status_display()],
    ]
    order_details_table = Table(order_details_data, colWidths=[1*inch, 1.5*inch], style=[('ALIGN', (0,0), (-1,-1), 'LEFT')])

    customer_table_data = [[Paragraph(customer_details, styles['CustomerInfo']), order_details_table]]
    customer_table = Table(customer_table_data, colWidths=[4*inch, 3*inch], style=[('VALIGN', (0,0), (-1,-1), 'TOP')])
    story.append(customer_table)
    story.append(Spacer(1, 0.4*inch))

    items_header = ['#', 'ITEM', 'QTY', 'UNIT PRICE', 'TOTAL']
    items_data = [items_header]
    
    for i, item in enumerate(sales_order.items.all(), 1):
        items_data.append([
            i,
            Paragraph(item.product.name, styles['Normal']),
            item.quantity,
            f"{item.unit_price:,.2f}",
            f"{item.subtotal:,.2f}"
        ])

    grand_total_text = f"{DEFAULT_CURRENCY_SYMBOL} {sales_order.total_amount:,.2f}"
    items_data.append(['', '', '', Paragraph('Grand Total', styles['TotalHeaderStyle']), Paragraph(grand_total_text, styles['BoldText'])])

    items_table = Table(items_data, colWidths=[0.4*inch, 3.6*inch, 0.7*inch, 1.1*inch, 1.2*inch])
    items_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor("#E0E5F2")),
        ('GRID', (0,0), (-1,-2), 1, colors.HexColor("#E0E5F2")),
        ('ALIGN', (2,1), (-1,-1), 'RIGHT'),
    ]))
    story.append(items_table)
    doc.build(story)
    return response

@login_required
@permission_required('sales.add_salesreturn', login_url='/admin/')
def create_sales_return(request):

    find_order_form = FindSalesOrderForm(request.GET or None)
    sales_order = None
    item_formset = None
    return_form = None

    if 'order_id' in request.GET and find_order_form.is_valid():
        order_id = find_order_form.cleaned_data['order_id']
        try:
            query = SalesOrder.objects.select_related('customer', 'warehouse').prefetch_related('items__product')
            if not request.user.is_superuser:
                user_warehouse = getattr(request.user, 'warehouse', None)
                if user_warehouse:
                    query = query.filter(warehouse=user_warehouse)
            sales_order = query.get(pk=order_id)

            if sales_order.status not in ['delivered', 'partially_delivered', 'out_for_delivery']:
                messages.warning(request, f"Sales Order #{sales_order.id} is not delivered yet.")
            
            sales_items_list = sales_order.items.all()
            return_form = SalesReturnForm(initial={'sales_order': sales_order, 'customer': sales_order.customer, 'warehouse': sales_order.warehouse})

            SalesReturnItemFormSet_Initial = formset_factory(SalesReturnItemForm, extra=len(sales_items_list), can_delete=False)
            item_formset = SalesReturnItemFormSet_Initial(prefix='items')

            for i, form in enumerate(item_formset.forms):
                if i < len(sales_items_list):
                    item = sales_items_list[i]
                    form.initial['product'] = item.product
                    form.initial['quantity'] = 0 
                    form.initial['unit_price'] = item.unit_price
                    form.sales_order_item = item

        except SalesOrder.DoesNotExist:
            messages.error(request, "Sales Order not found.")
            return redirect('sales:create_sales_return')

    if request.method == 'POST':
        sales_order_id = request.POST.get('sales_order') or (sales_order.id if sales_order else None)
        if sales_order_id:
            sales_order = get_object_or_404(SalesOrder, pk=sales_order_id)
        
        return_form = SalesReturnForm(request.POST)
        SalesReturnItemFormSet = formset_factory(SalesReturnItemForm, can_delete=False)
        item_formset = SalesReturnItemFormSet(request.POST, prefix='items')

        if return_form.is_valid() and item_formset.is_valid():
            try:
                with transaction.atomic():
                    sales_return = return_form.save(commit=False)
                    sales_return.sales_order = sales_order
                    sales_return.user = request.user
                    sales_return.customer = sales_order.customer
                    sales_return.warehouse = sales_order.warehouse
                    sales_return.save()

                    items_saved_count = 0
                    total_refund_value = Decimal(0)

                    for form in item_formset:
                        if form.is_valid():
                            data = form.cleaned_data
                            qty = data.get('quantity')
                            product = data.get('product')
                            
                            if qty and qty > 0:
                                net_price = form.initial.get('unit_price', 0)
                                
                                SalesReturnItem.objects.create(
                                    sales_return=sales_return,
                                    product=product,
                                    quantity=qty,
                                    unit_price=net_price
                                )
                                items_saved_count += 1
                                total_refund_value += (Decimal(qty) * Decimal(net_price))

                    if items_saved_count > 0:
                        SalesService.process_sales_return(sales_return, request.user)
                        
                        CustomerRefund.objects.get_or_create(
                            sales_return=sales_return,
                            defaults={
                                'customer': sales_return.customer,
                                'refund_amount': total_refund_value,
                                'status': 'Pending'
                            }
                        )
                        messages.success(request, f"Return processed. Refund of {total_refund_value} requested.")
                        return redirect('sales:sales_return_detail', pk=sales_return.id)
                    else:
                        sales_return.delete()
                        messages.warning(request, "No items returned.")

            except ValidationError as e:
                messages.error(request, e.message)
            except Exception as e:
                messages.error(request, f"Error: {e}")

    context = {
        'title': f'Process Return for SO-#{sales_order.id}' if sales_order else 'Create Sales Return',
        'find_order_form': find_order_form if not sales_order else None,
        'sales_order': sales_order,
        'return_form': return_form,
        'item_formset': item_formset,
    }
    return render(request, 'sales/create_sales_return.html', context)

@login_required
@permission_required('sales.view_salesreturn', login_url='/admin/')
def sales_return_detail(request, pk):
    sales_return = get_object_or_404(
        SalesReturn.objects.select_related('sales_order', 'customer', 'warehouse', 'user')
        .prefetch_related('items__product'),
        pk=pk
    )
    customer_refund = CustomerRefund.objects.filter(sales_return=sales_return).first()

    context = {
        'title': f'Sales Return #{sales_return.pk}',
        'sales_return': sales_return,
        'customer_refund': customer_refund,
        'DEFAULT_CURRENCY_SYMBOL': DEFAULT_CURRENCY_SYMBOL,
    }
    return render(request, 'sales/sales_return_detail.html', context)

@login_required
def validate_coupon(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            code = data.get('coupon_code', '').strip()
            total_amount = float(data.get('total_amount', 0))
            coupon = Coupon.objects.filter(code=code, active=True).first()

            if not coupon:
                return JsonResponse({'status': 'error', 'message': 'Invalid coupon code.'})
            if not coupon.is_valid():
                return JsonResponse({'status': 'error', 'message': 'Coupon expired or limit reached.'})
            
            discount_amount = 0
            if coupon.discount_type == 'percentage':
                discount_amount = (total_amount * float(coupon.discount_value)) / 100
            else:
                discount_amount = float(coupon.discount_value)

            return JsonResponse({
                'status': 'success',
                'discount_amount': round(discount_amount, 2),
                'message': 'Coupon applied successfully!'
            })
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)})
    return JsonResponse({'status': 'error', 'message': 'Invalid request'})


@login_required
def update_sales_order_status(request, pk):
    sales_order = get_object_or_404(SalesOrder, pk=pk)
    
    if request.method == 'POST':
        new_status = request.POST.get('status')

        allowed_manual = ['processing', 'out_for_delivery', 'cancelled', 'delivered']
        
        if new_status in allowed_manual:
            sales_order.status = new_status

            if new_status == 'delivered':
                sales_order.shipments.update(status='delivered', delivered_date=timezone.now())
                
            sales_order.save()
            messages.success(request, f"Status updated to {sales_order.get_status_display()}")
        else:
            messages.warning(request, "এই স্ট্যাটাসটি ম্যানুয়ালি পরিবর্তন করা যাবে না।")
            
    return redirect('sales:sales_order_detail', pk=pk)

@login_required
def search_products(request):
    query = request.GET.get('q', '').strip()
    warehouse_id = request.GET.get('warehouse_id')
    
    if query:
        products = Product.objects.filter(
            name__icontains=query, 
            is_active=True
        ).filter(
            Q(stock__warehouse_id=warehouse_id, stock__quantity__gt=0) |
            Q(product_type='gift_card') |
            Q(tracking_method='none') 
        ).distinct()
        
        results = []
        for p in products:
            results.append({
                'id': p.id,
                'text': f"{p.name} ({p.product_code or 'N/A'})",
                'sale_price': p.sale_price,
                'product_type': getattr(p, 'product_type', 'standard')
            })
        return JsonResponse({'results': results})
        
    return JsonResponse({'results': []})

@login_required
def search_products_for_sale(request):

    query = request.GET.get('q', '').strip()
    warehouse_id = request.GET.get('warehouse_id')
    
    if not query:
        return JsonResponse({'results': []})

    products = Product.objects.filter(
        Q(name__icontains=query) | Q(product_code__icontains=query),
        is_active=True
    )
    products = products.filter(
        Q(stock__warehouse_id=warehouse_id, stock__quantity__gt=0) |
        Q(product_type='gift_card') |
        Q(tracking_method='no_tracking')
    ).distinct()
    
    results = []
    for p in products:
        stock_qty = 0
        if p.product_type != 'gift_card':
            stock = p.stock_set.filter(warehouse_id=warehouse_id).first()
            if stock:
                stock_qty = stock.quantity
        else:
            stock_qty = 'N/A'

        results.append({
            'id': p.id,
            'text': f"{p.name} [{p.product_code}] (Stock: {stock_qty})",
            'sale_price': p.sale_price,
            'product_type': getattr(p, 'product_type', 'standard')
        })
        
    return JsonResponse({'results': results})