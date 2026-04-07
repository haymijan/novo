# purchase/views.py

from django.shortcuts import render, redirect, get_object_or_404
from django.http import HttpResponse, JsonResponse
from django.contrib.auth.decorators import login_required, permission_required
from django.db import transaction
from django.db.models import Sum, Q, F, Count, DecimalField
from django.core.paginator import Paginator
from django.contrib import messages
from django.forms import formset_factory
from datetime import timedelta
import json
from io import BytesIO
import os
from django.conf import settings
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import inch
from reportlab.lib.units import mm
from reportlab.lib.enums import TA_CENTER, TA_RIGHT, TA_LEFT
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.utils import timezone
from django.contrib.auth import get_user_model

from .models import PurchaseOrder, PurchaseOrderItem, ProductSupplier, StockTransferRequest, PurchaseReturn, PurchaseReturnItem
from stock.models import InventoryTransaction, LotSerialNumber, Location, Warehouse, Stock
from stock.services import StockService
from .forms import StockTransferFilterForm

from .forms import (
    PurchaseOrderForm, PurchaseOrderItemFormSet, DateRangeForm,
    PurchaseReceiveItemForm, ApproveForm, ApproveOrderItemFormSet,
    StockTransferRequestForm,
    ReceiveStockTransferForm,
    ProcessStockTransferForm,
    BranchPurchaseOrderItemFormSet,
    PurchaseReturnForm, PurchaseReturnItemFormSet
)
from products.models import Product
from partners.forms import SupplierForm
from partners.models import Supplier

from finance.gl.services import create_journal_entry
from finance.gl.models import ChartOfAccount, FinanceSettings
from decimal import Decimal

from .forms import ExchangeReceiveItemFormSet

from finance.ap.services import create_financial_records_from_po
from .services import create_financial_records_from_purchase_return

#=====================================================================================================

User = get_user_model()

DEFAULT_CURRENCY_SYMBOL = 'QAR '

def add_page_number(canvas, doc):
    page_num = canvas.getPageNumber()
    text = f"Page {page_num}"
    canvas.drawString(doc.leftMargin, inch / 2, text)

def apply_purchase_order_filters(queryset, request):
    start_date_str = request.GET.get('start_date')
    end_date_str = request.GET.get('end_date')
    status = request.GET.get('status')
    user_id = request.GET.get('user')
    warehouse_id = request.GET.get('warehouse')

    if start_date_str:
        start_date = timezone.datetime.strptime(start_date_str, '%Y-%m-%d')
        queryset = queryset.filter(order_date__gte=start_date)
    if end_date_str:
        end_date = timezone.datetime.strptime(end_date_str, '%Y-%m-%d') + timedelta(days=1)
        queryset = queryset.filter(order_date__lt=end_date)
    if status:
        queryset = queryset.filter(status=status)
    if user_id:
        queryset = queryset.filter(user_id=user_id)
    if warehouse_id:
        queryset = queryset.filter(warehouse_id=warehouse_id)
        
    return queryset

@login_required
@permission_required('purchase.view_purchaseorder', login_url='/admin/')
def purchase_order_list(request):
    purchase_orders_list = PurchaseOrder.objects.select_related('supplier', 'user', 'warehouse').all().order_by('-order_date')

    if not request.user.is_superuser:
        user_warehouse = getattr(request.user, 'warehouse', None)
        if user_warehouse:
            purchase_orders_list = purchase_orders_list.filter(warehouse=user_warehouse)
        else:
            purchase_orders_list = PurchaseOrder.objects.none()

    purchase_orders_list = apply_purchase_order_filters(purchase_orders_list, request)

    paginator = Paginator(purchase_orders_list, 10)
    page_number = request.GET.get('page')
    purchase_orders = paginator.get_page(page_number)
    context = {
        'purchase_orders': purchase_orders, 'title': 'All Purchase Orders',
        'DEFAULT_CURRENCY_SYMBOL': 'QAR',
        'users': User.objects.all(),
        'warehouses': Warehouse.objects.all(),
        'status_choices': PurchaseOrder.STATUS_CHOICES,
    }
    return render(request, 'purchase/purchase_order_list.html', context)

@login_required
@permission_required('purchase.add_purchaseorder', login_url='/admin/')
def create_purchase_order(request):
    is_branch_manager = not request.user.is_superuser
    
    if is_branch_manager:
        class BranchPurchaseOrderForm(PurchaseOrderForm):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                if 'supplier' in self.fields:
                    del self.fields['supplier']
        
        po_form_class = BranchPurchaseOrderForm
        formset_class = BranchPurchaseOrderItemFormSet
    else:
        po_form_class = PurchaseOrderForm
        formset_class = PurchaseOrderItemFormSet

    if request.method == 'POST':
        po_form = po_form_class(request.POST)
        formset = formset_class(request.POST, prefix='items', queryset=PurchaseOrderItem.objects.none())
        
        if po_form.is_valid() and formset.is_valid():
            with transaction.atomic():
                purchase_order = po_form.save(commit=False)
                purchase_order.user = request.user

                if is_branch_manager:
                    purchase_order.warehouse = getattr(request.user, 'warehouse', None)
                    purchase_order.status = 'purchase_request'
                    purchase_order.supplier = None
                    purchase_order.total_amount = 0.00
                else:
                    purchase_order.status = po_form.cleaned_data.get('status', 'draft')

                purchase_order.save()
                
                items = formset.save(commit=False)
                total_order_amount = 0

                for item in items:
                    item.purchase_order = purchase_order
                    if is_branch_manager:
                        item.unit_price = 0.00
                    
                    item.save()
                    if not is_branch_manager:
                        total_order_amount += item.total_price
                
                formset.save_m2m()
                if not is_branch_manager:
                    purchase_order.total_amount = total_order_amount
                    purchase_order.save(update_fields=['total_amount'])

            messages.success(request, f"Purchase Request PO-{purchase_order.pk} created successfully!")
            return redirect('purchase:purchase_order_detail', pk=purchase_order.pk)
    else:
        initial_data = {
            'user': request.user,
            'warehouse': getattr(request.user, 'warehouse', None),
            'status': 'purchase_request' if is_branch_manager else 'draft',
        }
        po_form = po_form_class(initial=initial_data)
        formset = formset_class(prefix='items', queryset=PurchaseOrderItem.objects.none())

    context = {
        'po_form': po_form,
        'formset': formset,
        'supplier_form': SupplierForm(),
        'title': 'Create New Purchase Request' if is_branch_manager else 'Create New Purchase Order',
        'is_branch_manager': is_branch_manager,
    }
    return render(request, 'purchase/create_purchase_order.html', context)

@login_required
@permission_required('purchase.view_purchaseorder', login_url='/admin/')
def purchase_order_detail(request, pk):
    purchase_order = get_object_or_404(PurchaseOrder.objects.select_related('supplier').prefetch_related('items__product'), pk=pk)
    
    items_qs = purchase_order.items.all().select_related('product').exclude(product__isnull=True)
    
    approve_form = ApproveForm(request.POST or None, initial={'supplier': purchase_order.supplier})
    approve_formset = ApproveOrderItemFormSet(request.POST or None, queryset=items_qs, prefix='items')

    if request.method == 'POST':
        action = request.POST.get('action')
        
        if action == 'approve_request' and request.user.is_superuser:
            if purchase_order.status == 'purchase_request' and approve_form.is_valid() and approve_formset.is_valid():
                supplier = approve_form.cleaned_data['supplier']
                with transaction.atomic():
                    purchase_order.supplier = supplier
                    purchase_order.status = 'confirmed'
                    approve_formset.save()
                    total_amount = sum(item.total_price for item in items_qs)
                    purchase_order.total_amount = total_amount
                    purchase_order.save(update_fields=['supplier', 'status', 'total_amount'])
                messages.success(request, f"Purchase Request PO-{purchase_order.pk} has been approved and confirmed.")
                return redirect('purchase:purchase_order_detail', pk=purchase_order.pk)
            else:
                 messages.error(request, "Please correct the errors below.")
                 if approve_form.errors:
                     messages.error(request, f"Supplier Form Error: {approve_form.errors}")
                 if approve_formset.errors:
                     for i, errors in enumerate(approve_formset.errors):
                         if errors:
                             messages.error(request, f"Item {i+1} Errors: {errors.as_text()}")
        
        elif action == 'confirm' and request.user.is_superuser:
            if purchase_order.status in ['draft']:
                purchase_order.status = 'confirmed'
                purchase_order.save()
                messages.success(request, f"Purchase Order PO-{purchase_order.pk} has been confirmed.")
                return redirect('purchase:purchase_order_detail', pk=purchase_order.pk)
        elif action == 'cancel':
            if purchase_order.status not in ['received', 'cancelled']:
                purchase_order.status = 'cancelled'
                purchase_order.save()
                messages.warning(request, f"Purchase Order PO-{purchase_order.pk} has been cancelled.")
                return redirect('purchase:purchase_order_detail', pk=purchase_order.pk)

    context = {
        'purchase_order': purchase_order, 
        'title': f'Purchase Order: PO-{purchase_order.id}', 
        'DEFAULT_CURRENCY_SYMBOL': DEFAULT_CURRENCY_SYMBOL,
        'approve_form': approve_form,
        'approve_formset': approve_formset,
    }
    return render(request, 'purchase/purchase_order_detail.html', context)

@login_required
@permission_required('purchase.change_purchaseorder', login_url='/admin/')
def edit_purchase_order(request, pk):
    purchase_order = get_object_or_404(PurchaseOrder, pk=pk)
    
    if purchase_order.status not in ['draft', 'purchase_request']:
        messages.error(request, f"Cannot edit a {purchase_order.get_status_display()} purchase order.")
        return redirect('purchase:purchase_order_detail', pk=pk)
    
    if request.user.is_superuser:
        po_form = PurchaseOrderForm(request.POST or None, instance=purchase_order)
    else:
        class BranchPurchaseOrderForm(PurchaseOrderForm):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                del self.fields['supplier']
        po_form = BranchPurchaseOrderForm(request.POST or None, instance=purchase_order)

    formset = PurchaseOrderItemFormSet(request.POST or None, instance=purchase_order, prefix='items')
    
    if request.method == 'POST':
        if po_form.is_valid() and formset.is_valid():
            with transaction.atomic():
                po_form.save()
                formset.save()
            return redirect('purchase:purchase_order_detail', pk=pk)
    else:
        po_form = PurchaseOrderForm(instance=purchase_order)
        if not request.user.is_superuser:
            po_form = BranchPurchaseOrderForm(instance=purchase_order)

        formset = PurchaseOrderItemFormSet(instance=purchase_order, prefix='items')
        
    context = {
        'po_form': po_form, 
        'formset': formset, 
        'title': f'Edit Purchase Order: PO-{purchase_order.id}',
        'is_superuser': request.user.is_superuser,
    }
    return render(request, 'purchase/edit_purchase_order.html', context)

@login_required
@permission_required('purchase.view_purchaseorder', raise_exception=True)
def export_single_purchase_order_pdf(request, pk):
    purchase_order = get_object_or_404(PurchaseOrder.objects.select_related('supplier', 'warehouse', 'user'), pk=pk)

    is_branch_manager = not request.user.is_superuser
    is_requisition = purchase_order.status == 'purchase_request'

    show_price = not is_branch_manager and not is_requisition

    pdf_title = "PURCHASE REQUISITION" if is_requisition else "PURCHASE ORDER"
    filename_prefix = "PR" if is_requisition else "PO"

    supplier_name_for_file = purchase_order.supplier.name if purchase_order.supplier else "No_Supplier"
    
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{filename_prefix}-{purchase_order.pk}_{supplier_name_for_file}.pdf"'

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=30, leftMargin=30, topMargin=30, bottomMargin=30)
    story = []

    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name='TitleStyle', fontSize=22, fontName='Helvetica-Bold', alignment=TA_RIGHT, textColor=colors.HexColor("#2B3674")))
    styles.add(ParagraphStyle(name='CompanyInfo', fontSize=9, fontName='Helvetica', alignment=TA_RIGHT, leading=12))
    styles.add(ParagraphStyle(name='SupplierInfo', fontSize=10, fontName='Helvetica', leading=14))
    styles.add(ParagraphStyle(name='HeaderStyle', fontSize=10, fontName='Helvetica-Bold', alignment=TA_LEFT))
    styles.add(ParagraphStyle(name='TotalHeaderStyle', fontSize=10, fontName='Helvetica-Bold', alignment=TA_RIGHT))
    styles.add(ParagraphStyle(name='SignatureStyle', fontSize=10, fontName='Helvetica', alignment=TA_CENTER))
    styles.add(ParagraphStyle(name='BoldText', fontName='Helvetica-Bold'))

    logo_path = os.path.join(settings.STATICFILES_DIRS[0], 'images', 'logo.png')
    logo = Image(logo_path, width=1.5*inch, height=0.5*inch)
    company_info = "<b>NOVO ERP Solutions</b><br/>Doha, Qatar"
    
    header_data = [[logo, Paragraph(pdf_title, styles['TitleStyle'])]]
    header_table = Table(header_data, colWidths=[3*inch, 4.5*inch], style=[('VALIGN', (0,0), (-1,-1), 'TOP')])
    story.append(header_table)
    story.append(Spacer(1, 0.1*inch))
    story.append(Paragraph(company_info, styles['CompanyInfo']))
    story.append(Spacer(1, 0.5*inch))

    if purchase_order.supplier:
        supplier_phone = getattr(purchase_order.supplier, 'phone', '')
        supplier_details = f"""
        <b>SUPPLIER:</b><br/>
        {purchase_order.supplier.name}<br/>
        {purchase_order.supplier.address or ''}<br/>
        {purchase_order.supplier.email or ''}<br/>
        {supplier_phone}
        """
    else:
        supplier_details = "<b>SUPPLIER:</b><br/>N/A"
    
    order_details_data = [
        [Paragraph(f'{filename_prefix} Number:', styles['Normal']), Paragraph(f'{filename_prefix}-{purchase_order.pk}', styles['BoldText'])],
        [Paragraph('Order Date:', styles['Normal']), Paragraph(purchase_order.order_date.strftime('%d %b, %Y'), styles['BoldText'])],
        [Paragraph('Status:', styles['Normal']), Paragraph(purchase_order.get_status_display(), styles['BoldText'])],
        [Paragraph('Branch:', styles['Normal']), Paragraph(purchase_order.warehouse.name if purchase_order.warehouse else 'N/A', styles['BoldText'])],
    ]
    order_details_table = Table(order_details_data, colWidths=[1.2*inch, 1.6*inch])

    supplier_table_data = [[Paragraph(supplier_details, styles['SupplierInfo']), order_details_table]]
    supplier_table = Table(supplier_table_data, colWidths=[4.5*inch, 3*inch], style=[('VALIGN', (0,0), (-1,-1), 'TOP')])
    story.append(supplier_table)
    story.append(Spacer(1, 0.4*inch))

    items_data = []

    if show_price:
        items_header = ['#', 'ITEM DESCRIPTION', 'QTY', 'UNIT PRICE', 'TOTAL']
        items_data.append(items_header)
        for i, item in enumerate(purchase_order.items.all(), 1):
            subtotal = item.quantity * item.unit_price
            items_data.append([i, item.product.name, item.quantity, f"{item.unit_price:,.2f}", f"{subtotal:,.2f}"])

        grand_total_text = f"{settings.DEFAULT_CURRENCY_SYMBOL} {purchase_order.total_amount:,.2f}"
        items_data.append(['', '', '', Paragraph('Grand Total', styles['TotalHeaderStyle']), Paragraph(grand_total_text, styles['BoldText'])])

        col_widths = [0.4*inch, 3.6*inch, 0.7*inch, 1.1*inch, 1.2*inch]
        table_style = TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.HexColor("#E0E5F2")),
            ('TEXTCOLOR', (0,0), (-1,0), colors.HexColor("#2B3674")),
            ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
            ('GRID', (0,0), (-1,-2), 1, colors.HexColor("#CCCCCC")),
            ('ALIGN', (2,1), (-1,-1), 'RIGHT'),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ('GRID', (3,-1), (-1,-1), 1, colors.HexColor("#CCCCCC")),
            ('SPAN', (0, -1), (2, -1)),
            ('ALIGN', (4,-1), (4,-1), 'RIGHT'),
        ])
    else:
        items_header = ['#', 'ITEM DESCRIPTION', 'QTY']
        items_data.append(items_header)
        for i, item in enumerate(purchase_order.items.all(), 1):
            items_data.append([i, item.product.name, item.quantity])
        
        col_widths = [0.4*inch, 6.4*inch, 0.7*inch]
        table_style = TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.HexColor("#E0E5F2")),
            ('TEXTCOLOR', (0,0), (-1,0), colors.HexColor("#2B3674")),
            ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
            ('GRID', (0,0), (-1,-1), 1, colors.HexColor("#CCCCCC")),
            ('ALIGN', (2,1), (-1,-1), 'RIGHT'),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ])

    items_table = Table(items_data, colWidths=col_widths)
    items_table.setStyle(table_style)
    story.append(items_table)
    story.append(Spacer(1, 1.2*inch))

    signature_data = [
        [Paragraph('--------------------------------<br/>Prepared By', styles['SignatureStyle']),
         Paragraph('--------------------------------<br/>Approved By', styles['SignatureStyle'])]
    ]
    signature_table = Table(signature_data, colWidths=[3.5*inch, 3.5*inch], hAlign='CENTER')
    story.append(signature_table)

    doc.build(story)
    
    buffer.seek(0)
    response.write(buffer.getvalue())
    return response

@login_required
@permission_required('purchase.view_purchaseorder', raise_exception=True)
def export_single_purchase_receipt_pdf(request, pk):
    purchase_order = get_object_or_404(PurchaseOrder.objects.select_related('supplier', 'warehouse'), pk=pk)
    related_transactions = InventoryTransaction.objects.filter(
        notes__startswith=f"Received PO-{purchase_order.id}"
    ).select_related('product', 'lot_serial', 'lot_serial__location', 'destination_location')

    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="GRN-{purchase_order.pk}.pdf"'
    
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=30, leftMargin=30, topMargin=30, bottomMargin=30)
    story = []

    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name='TitleStyle', fontSize=22, fontName='Helvetica-Bold', alignment=TA_RIGHT, textColor=colors.HexColor("#2B3674")))
    styles.add(ParagraphStyle(name='CompanyInfo', fontSize=9, fontName='Helvetica', alignment=TA_RIGHT, leading=12))
    styles.add(ParagraphStyle(name='SupplierInfo', fontSize=10, fontName='Helvetica', leading=14))
    styles.add(ParagraphStyle(name='SignatureStyle', fontSize=10, fontName='Helvetica', alignment=TA_CENTER))

    logo_path = os.path.join(settings.STATICFILES_DIRS[0], 'images', 'logo.png')
    logo = Image(logo_path, width=1.5*inch, height=0.5*inch)
    company_info = "<b>NOVO ERP Solutions</b><br/>Doha, Qatar"
    
    header_data = [[logo, Paragraph("Goods Received Note (GRN)", styles['TitleStyle'])]]
    header_table = Table(header_data, colWidths=[3*inch, 4.5*inch], style=[('VALIGN', (0,0), (-1,-1), 'TOP')])
    story.append(header_table)
    story.append(Spacer(1, 0.1*inch))
    story.append(Paragraph(company_info, styles['CompanyInfo']))
    story.append(Spacer(1, 0.5*inch))
    receipt_details_data = [
        [Paragraph('<b>Receipt Date:</b>', styles['Normal']), Paragraph(timezone.now().strftime('%d %b, %Y'), styles['Normal'])],
        [Paragraph('<b>PO Number:</b>', styles['Normal']), Paragraph(f'PO-{purchase_order.pk}', styles['Normal'])],
        [Paragraph('<b>Supplier:</b>', styles['Normal']), Paragraph(purchase_order.supplier.name if purchase_order.supplier else 'N/A', styles['Normal'])],
        [Paragraph('<b>Received At:</b>', styles['Normal']), Paragraph(purchase_order.warehouse.name if purchase_order.warehouse else 'N/A', styles['Normal'])],
    ]
    receipt_details_table = Table(receipt_details_data, colWidths=[1.2*inch, 6.3*inch])
    story.append(receipt_details_table)
    story.append(Spacer(1, 0.4*inch))
    items_header = ['#', 'ITEM DESCRIPTION', 'RECEIVED QTY', 'DESTINATION', 'LOT/SERIAL', 'EXPIRY']
    items_data = [items_header]

    table_style_commands = [
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor("#E0E5F2")),
        ('TEXTCOLOR', (0,0), (-1,0), colors.HexColor("#2B3674")),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('GRID', (0,0), (-1,-1), 1, colors.HexColor("#CCCCCC")),
        ('ALIGN', (2,1), (2,-1), 'CENTER'),
        ('ALIGN', (5,1), (5,-1), 'CENTER'),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
    ]

    if not related_transactions.exists():
        items_data.append([Paragraph("No items have been marked as received for this order yet.", styles['Normal'])])
        table_style_commands.append(('SPAN', (0, 1), (-1, 1)))
    else:
        for i, transaction in enumerate(related_transactions, 1):
            items_data.append([
                i,
                transaction.product.name,
                transaction.quantity,
                str(transaction.destination_location),
                str(transaction.lot_serial.lot_number) if transaction.lot_serial else "N/A",
                transaction.lot_serial.expiration_date.strftime('%d %b, %Y') if transaction.lot_serial and transaction.lot_serial.expiration_date else "N/A"
            ])
    
    items_table = Table(items_data, colWidths=[0.4*inch, 2.6*inch, 1*inch, 1.2*inch, 1.3*inch, 1*inch])
    items_table.setStyle(TableStyle(table_style_commands))
    story.append(items_table)
    story.append(Spacer(1, 1.2*inch))

    signature_data = [
        [Paragraph('--------------------------------<br/>Received By', styles['SignatureStyle']),
         Paragraph('--------------------------------<br/>Store Keeper', styles['SignatureStyle'])]
    ]
    signature_table = Table(signature_data, colWidths=[3.5*inch, 3.5*inch], hAlign='CENTER')
    story.append(signature_table)

    doc.build(story)
    
    buffer.seek(0)
    response.write(buffer.getvalue())
    return response

@login_required
def get_products_by_supplier_ajax(request):
    supplier_id = request.GET.get('supplier_id')
    
    if not supplier_id:
        products_qs = Product.objects.filter(is_active=True).values('id', 'name', 'price').order_by('name')
        return JsonResponse({'products': list(products_qs)})

    products_with_supplier_prices_qs = ProductSupplier.objects.filter(supplier_id=supplier_id).values('product_id', 'product__name', 'price')
    
    products_data = []
    for item in products_with_supplier_prices_qs:
        products_data.append({
            'id': item['product_id'],
            'name': item['product__name'],
            'price': item['price']
        })
    
    return JsonResponse({'products': products_data})

@login_required
def get_product_price_by_supplier_ajax(request):
    product_id = request.GET.get('product_id')
    supplier_id = request.GET.get('supplier_id')
    
    if not product_id:
        return JsonResponse({'error': 'Product ID is required'}, status=400)

    if not supplier_id:
        try:
            product = Product.objects.get(id=product_id)
            return JsonResponse({'purchase_price': product.price})
        except ObjectDoesNotExist:
            return JsonResponse({'error': 'Product not found'}, status=404)

    try:
        product_supplier = ProductSupplier.objects.get(product_id=product_id, supplier_id=supplier_id)
        price = product_supplier.price
    except ObjectDoesNotExist:
        try:
            product = Product.objects.get(id=product_id)
            price = product.price
        except ObjectDoesNotExist:
            return JsonResponse({'error': 'Product not found'}, status=404)

    return JsonResponse({'purchase_price': price})

@login_required
@permission_required('purchase.view_purchaseorder', login_url='/admin/')
def export_purchase_orders_excel(request):
    wb = Workbook()
    ws = wb.active
    ws.title = "Purchase Orders"
    headers = ['PO #', 'Supplier', 'Order Date', 'Expected Delivery', 'Status', 'Total Amount']
    ws.append(headers)
    for cell in ws[1]:
        cell.font = Font(bold=True, color="2B3674")
        cell.alignment = Alignment(horizontal="center", vertical="center")

    purchase_orders = PurchaseOrder.objects.select_related('supplier', 'warehouse').all().order_by('-order_date')
    filtered_result = apply_purchase_order_filters(purchase_orders, request)

    if isinstance(filtered_result, tuple):
        purchase_orders, _ = filtered_result
    else:
        purchase_orders = filtered_result

    if not hasattr(purchase_orders, "__iter__"):
        purchase_orders = [purchase_orders]

    for po in purchase_orders:
        order_date_naive = po.order_date.strftime('%Y-%m-%d %H:%M') if po.order_date else ''
        delivery_date_naive = po.expected_delivery_date.strftime('%Y-%m-%d') if po.expected_delivery_date else ''

        ws.append([
            f"PO-{po.id}",
            po.supplier.name if po.supplier else 'N/A',
            order_date_naive,
            delivery_date_naive,
            po.get_status_display(),
            po.total_amount
        ])

    for col in ws.columns:
        max_length = 0
        column = col[0].column_letter
        for cell in col:
            try:
                if cell.value and len(str(cell.value)) > max_length:
                    max_length = len(str(cell.value))
            except:
                pass
        adjusted_width = (max_length + 2)
        ws.column_dimensions[column].width = adjusted_width

    response = HttpResponse(content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    response['Content-Disposition'] = 'attachment; filename="purchase_orders.xlsx"'
    wb.save(response)
    return response


@login_required
@permission_required('purchase.view_purchaseorder', login_url='/admin/')
def export_purchase_orders_pdf(request):
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=30, leftMargin=30, topMargin=30, bottomMargin=30)
    story = []

    # --- Styles ---
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name='TitleStyle', fontSize=18, fontName='Helvetica-Bold',
                              alignment=TA_CENTER, textColor=colors.HexColor("#2B3674")))
    styles.add(ParagraphStyle(name='TableHeader', fontSize=9, fontName='Helvetica-Bold',
                              alignment=TA_CENTER, textColor=colors.HexColor("#2B3674")))
    styles.add(ParagraphStyle(name='TableCell', fontSize=8, fontName='Helvetica', alignment=TA_CENTER))

    # --- Header Section ---
    logo_path = os.path.join(settings.STATICFILES_DIRS[0], 'images', 'logo.png')
    if os.path.exists(logo_path):
        logo = Image(logo_path, width=1.7*inch, height=0.4*inch)
        header_table = Table([[logo, Paragraph("Purchase Orders Report", styles['TitleStyle'])]],
                             colWidths=[2*inch, 4.5*inch])
        header_table.setStyle(TableStyle([('VALIGN', (0,0), (-1,-1), 'MIDDLE')]))
        story.append(header_table)
    else:
        story.append(Paragraph("Purchase Orders Report", styles['TitleStyle']))

    story.append(Spacer(1, 0.4 * inch))

    # --- Table Header ---
    data = [[
        Paragraph(h, styles['TableHeader']) for h in
        ['PO #', 'Supplier', 'Order Date', 'Expected Delivery', 'Status', 'Total']
    ]]

    # --- Fetch Data ---
    purchase_orders = PurchaseOrder.objects.select_related('supplier', 'warehouse').all().order_by('-order_date')
    filtered_result = apply_purchase_order_filters(purchase_orders, request)

    if isinstance(filtered_result, tuple):
        purchase_orders, _ = filtered_result
    else:
        purchase_orders = filtered_result

    if not hasattr(purchase_orders, "__iter__"):
        purchase_orders = [purchase_orders]

    # --- Table Data ---
    if not purchase_orders:
        data.append([Paragraph("No purchase orders found for the selected filters.", styles['TableCell'])])
        table_style = [
            ('SPAN', (0, 1), (-1, 1)),
            ('ALIGN', (0, 1), (-1, 1), 'CENTER')
        ]
        col_widths = [6.5*inch]
    else:
        for po in purchase_orders:
            data.append([
                Paragraph(f"PO-{po.id}", styles['TableCell']),
                Paragraph(po.supplier.name if po.supplier else 'N/A', styles['TableCell']),
                Paragraph(po.order_date.strftime('%d %b %Y') if po.order_date else 'N/A', styles['TableCell']),
                Paragraph(po.expected_delivery_date.strftime('%d %b %Y') if po.expected_delivery_date else 'N/A', styles['TableCell']),
                Paragraph(po.get_status_display(), styles['TableCell']),
                Paragraph(f"{DEFAULT_CURRENCY_SYMBOL}{po.total_amount:.2f}", styles['TableCell'])
            ])
        table_style = []
        col_widths = [0.8*inch, 2.0*inch, 1.2*inch, 1.2*inch, 1*inch, 1.2*inch]

    # --- Table Styling ---
    table = Table(data, colWidths=col_widths)
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#E0E5F2")),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.HexColor("#2B3674")),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#CCCCCC")),
    ] + table_style))

    story.append(table)

    def add_page_number(canvas, doc):
        page_num = canvas.getPageNumber()
        canvas.setFont("Helvetica", 8)
        canvas.drawRightString(200*mm, 15*mm, f"Page {page_num}")

    doc.build(story, onFirstPage=add_page_number, onLaterPages=add_page_number)

    buffer.seek(0)
    response = HttpResponse(buffer, content_type='application/pdf')
    response['Content-Disposition'] = 'attachment; filename="purchase_orders.pdf"'
    return response

@login_required
@permission_required('purchase.change_purchaseorder', login_url='/admin/')
def receive_purchase_order(request, pk):
    purchase_order = get_object_or_404(PurchaseOrder.objects.select_related('supplier', 'warehouse'), pk=pk)

    if purchase_order.status not in ['confirmed', 'partially_received']:
        messages.warning(request, f"Purchase order {purchase_order.id} is not ready to be received.")
        return redirect('purchase:purchase_order_detail', pk=pk)

    items_to_receive = purchase_order.items.filter(quantity__gt=F('quantity_received')).select_related('product')

    if not items_to_receive.exists():
        messages.info(request, "All items for this order are already fully received.")
        return redirect('purchase:purchase_order_detail', pk=pk)

    PurchaseReceiveFormSet = formset_factory(PurchaseReceiveItemForm, extra=0)
    
    form_kwargs = {'warehouse': purchase_order.warehouse}

    if request.method == 'POST':
        formset = PurchaseReceiveFormSet(request.POST, form_kwargs=form_kwargs)
        
        if formset.is_valid():
            try:
                with transaction.atomic():
                    received_items_count = 0
                    for form in formset:
                        data = form.cleaned_data
                        quantity_received = data.get('quantity_to_receive', 0)

                        if quantity_received > 0:
                            po_item = get_object_or_404(PurchaseOrderItem, id=data['purchase_order_item_id'])
                            lot_number = data.get('lot_number')

                            if po_item.product.tracking_method in ['lot', 'serial'] and lot_number:
                                
                                if LotSerialNumber.objects.filter(
                                    product=po_item.product,
                                    lot_number=lot_number
                                ).exists():
                                    
                                    raise ValidationError(
                                        f"ত্রুটি: '{po_item.product.name}' প্রোডাক্টের জন্য লট নম্বর '{lot_number}' ইতিমধ্যে সিস্টেমে বিদ্যমান। "
                                        f"এটি একটি নতুন ব্যাচ হলে, অনুগ্রহ করে সম্পূর্ণ নতুন এবং ইউনিক একটি লট নম্বর দিন।"
                                    )
                            received_items_count += 1
                            
                            if quantity_received > (po_item.quantity - po_item.quantity_received):
                                raise ValidationError(f"Received quantity for {po_item.product.name} exceeds remaining quantity.")

                            StockService.add_stock(
                                product=po_item.product,
                                warehouse=purchase_order.warehouse,
                                quantity=quantity_received,
                                user=request.user,
                                content_object=purchase_order,
                                location=data['destination_location'],
                                lot_number=lot_number,
                                expiration_date=data.get('expiration_date'),
                                cost_price=po_item.unit_price,
                                purchase_order_item=po_item
                            )
                    
                    if received_items_count > 0:
                        purchase_order.update_status()
                        
                        if purchase_order.status == 'received':
                            try:
                                create_financial_records_from_po(purchase_order)
                                messages.success(request, f"Stock received and financial entries created for PO-{purchase_order.pk}")
                            except Exception as e:
                                messages.error(request, f"Stock was received, but failed to create financial entries: {e}")
                        else:
                            messages.success(request, f"Stock partially received for PO-{purchase_order.pk}")
                            
                        return redirect('purchase:purchase_order_detail', pk=pk)
                    else:
                        messages.warning(request, "No items were marked as received.")

            except (ValidationError, ValueError) as e:
                messages.error(request, str(e))
    else:
        initial_data = []
        for item in items_to_receive:
            initial_data.append({
                'purchase_order_item_id': item.id,
                'quantity_to_receive': item.quantity - item.quantity_received,
            })
        
        formset = PurchaseReceiveFormSet(initial=initial_data, form_kwargs=form_kwargs)
    form_and_items = zip(formset.forms, items_to_receive)
    context = {
        'title': f'Receive Stock for PO-{purchase_order.pk}',
        'purchase_order': purchase_order,
        'form_and_items': form_and_items,
        'formset': formset,
    }
    return render(request, 'purchase/receive_purchase_order.html', context)

@login_required
@permission_required('purchase.add_stocktransferrequest', login_url='/admin/')
def create_stock_transfer_request(request):
    form = StockTransferRequestForm(request.POST or None, user=request.user)

    if request.method == 'POST':
        if form.is_valid():
            with transaction.atomic():
                transfer_request = form.save(commit=False)
                transfer_request.user = request.user
                transfer_request.status = 'requested'
                requester_warehouse = getattr(request.user, 'warehouse', None)
                if requester_warehouse:
                    transfer_request.destination_warehouse = requester_warehouse
                    transfer_request.source_warehouse = form.cleaned_data['source_warehouse']
                transfer_request.save()
            messages.success(request, f"Stock transfer request #{transfer_request.pk} for {transfer_request.product.name} has been submitted.")
            return redirect('purchase:stock_transfer_request_list')
    
    context = {
        'form': form,
        'title': 'Create Stock Transfer Request',
    }
    return render(request, 'purchase/create_stock_transfer_request.html', context)

@login_required
@permission_required('purchase.view_stocktransferrequest', login_url='/admin/')
def stock_transfer_request_list(request):
    transfer_requests = StockTransferRequest.objects.all().select_related('user', 'product', 'source_warehouse', 'destination_warehouse').order_by('-requested_at')
    
    if not request.user.is_superuser:
        user_warehouse = getattr(request.user, 'warehouse', None)
        if user_warehouse:
            transfer_requests = transfer_requests.filter(
                Q(destination_warehouse=user_warehouse) | Q(source_warehouse=user_warehouse)
            )
        else:
            transfer_requests = StockTransferRequest.objects.none()

    filter_form = StockTransferFilterForm(request.GET or None, user=request.user)
    if filter_form.is_valid():
        start_date = filter_form.cleaned_data.get('start_date')
        end_date = filter_form.cleaned_data.get('end_date')
        product = filter_form.cleaned_data.get('product')
        source_warehouse = filter_form.cleaned_data.get('source_warehouse')
        destination_warehouse = filter_form.cleaned_data.get('destination_warehouse')
        status = filter_form.cleaned_data.get('status')
        requested_by = filter_form.cleaned_data.get('requested_by') # <-- নতুন

        if start_date:
            transfer_requests = transfer_requests.filter(requested_at__date__gte=start_date)
        if end_date:
            transfer_requests = transfer_requests.filter(requested_at__date__lte=end_date)
        if product:
            transfer_requests = transfer_requests.filter(product=product)
        if source_warehouse:
            transfer_requests = transfer_requests.filter(source_warehouse=source_warehouse)
        if destination_warehouse:
            transfer_requests = transfer_requests.filter(destination_warehouse=destination_warehouse)
        if status:
            transfer_requests = transfer_requests.filter(status=status)
        if requested_by:
            transfer_requests = transfer_requests.filter(user=requested_by)
    
    context = {
        'transfer_requests': transfer_requests,
        'title': 'Stock Transfer Requests',
        'filter_form': filter_form,
    }
    return render(request, 'purchase/stock_transfer_request_list.html', context)

@login_required
@permission_required('purchase.view_stocktransferrequest', login_url='/admin/')
def stock_transfer_detail(request, pk):
    transfer_request = get_object_or_404(StockTransferRequest.objects.select_related('product', 'source_warehouse', 'destination_warehouse', 'user'), pk=pk)
    
    process_form = None
    receive_form = None
    user_warehouse = getattr(request.user, 'warehouse', None)

    is_source_manager = (transfer_request.source_warehouse == user_warehouse)
    is_destination_manager = (transfer_request.destination_warehouse == user_warehouse)
    if transfer_request.status == 'approved' and is_source_manager:
        product = transfer_request.product
        
        if request.method == 'POST' and 'process_transfer' in request.POST:
            process_form = ProcessStockTransferForm(request.POST)
            source_location_id = request.POST.get('source_location')
            process_form.fields['source_location'].queryset = Location.objects.filter(warehouse=user_warehouse)
            if source_location_id and product.tracking_method in ['lot', 'serial']:
                process_form.fields['lot_serial'].queryset = LotSerialNumber.objects.filter(
                    product=product, location_id=source_location_id, quantity__gt=0)

            if process_form.is_valid():
                quantity_to_transfer = process_form.cleaned_data['quantity_to_transfer']
                source_location = process_form.cleaned_data['source_location']
                lot_serial_obj = process_form.cleaned_data.get('lot_serial')

                if product.tracking_method in ['lot', 'serial'] and not lot_serial_obj:
                    messages.error(request, "For a lot-tracked product, you must select a Lot/Serial Number.")
                else:
                    try:
                        with transaction.atomic():
                            StockService.change_stock(
                                product=product,
                                warehouse=transfer_request.source_warehouse,
                                quantity_change=-quantity_to_transfer,
                                transaction_type='transfer_out',
                                user=request.user,
                                content_object=transfer_request,
                                location=source_location,
                                lot_serial=lot_serial_obj,
                                notes=f"Transfer OUT for request #{transfer_request.pk}",
                                from_warehouse=transfer_request.source_warehouse,
                                to_warehouse=transfer_request.destination_warehouse
                            )
                            
                            transfer_request.status = 'in_transit'
                            transfer_request.quantity_transferred = quantity_to_transfer
                            transfer_request.dispatched_lot = lot_serial_obj 
                            transfer_request.save()
                            messages.success(request, f"Stock transfer dispatched successfully.")
                        return redirect('purchase:stock_transfer_detail', pk=pk)
                    except (ValueError, ValidationError) as e:
                        messages.error(request, str(e))
            else:
                messages.error(request, "Please correct the errors in the dispatch form.")
        else:
            # GET request
            process_form = ProcessStockTransferForm()
            locations_with_stock = Location.objects.filter(
                warehouse=user_warehouse, 
                lots__product=product, 
                lots__quantity__gt=0
            ).distinct()

            process_form.fields['source_location'].queryset = locations_with_stock

    if transfer_request.status == 'in_transit' and is_destination_manager:
        initial_data = {}
        if transfer_request.dispatched_lot:
            initial_data['lot_number'] = transfer_request.dispatched_lot.lot_number
            initial_data['expiration_date'] = transfer_request.dispatched_lot.expiration_date
        
        receive_form = ReceiveStockTransferForm(initial=initial_data)
        receive_form.fields['destination_location'].queryset = Location.objects.filter(warehouse=user_warehouse)

    context = {
        'transfer_request': transfer_request,
        'title': f"Stock Transfer Request #{transfer_request.pk}",
        'process_form': process_form,
        'receive_form': receive_form,
        'product_is_tracked': transfer_request.product.tracking_method in ['lot', 'serial']
    }
    return render(request, 'purchase/stock_transfer_detail.html', context)

@login_required
@permission_required('purchase.approve_stocktransferrequest', login_url='/admin/')
def approve_stock_transfer(request, pk):
    transfer_request = get_object_or_404(StockTransferRequest, pk=pk)
    
    if not request.user.is_superuser:
        messages.error(request, "You do not have permission to perform this action.")
        return redirect('purchase:stock_transfer_detail', pk=pk)

    if request.method == 'POST':
        action = request.POST.get('action')
        with transaction.atomic():
            if action == 'approve' and transfer_request.status == 'requested':
                transfer_request.status = 'approved'
                transfer_request.approved_at = timezone.now()
                transfer_request.save()
                messages.success(request, f"Stock transfer request #{transfer_request.pk} has been approved.")
            elif action == 'reject' and transfer_request.status == 'requested':
                transfer_request.status = 'rejected'
                transfer_request.save()
                messages.warning(request, f"Stock transfer request #{transfer_request.pk} has been rejected.")
            
    return redirect('purchase:stock_transfer_detail', pk=pk)

@login_required
@permission_required('purchase.change_stocktransferrequest', login_url='/admin/')
def receive_stock_transfer(request, pk):
    transfer_request = get_object_or_404(StockTransferRequest.objects.select_related('product', 'dispatched_lot'), pk=pk)
    user_warehouse = getattr(request.user, 'warehouse', None)

    if transfer_request.destination_warehouse != user_warehouse and not request.user.is_superuser:
        messages.error(request, "You do not have permission to receive this transfer.")
        return redirect('purchase:stock_transfer_detail', pk=pk)

    if request.method == 'POST':
        form = ReceiveStockTransferForm(request.POST)
        form.fields['destination_location'].queryset = Location.objects.filter(warehouse=user_warehouse)

        if form.is_valid():
            quantity_received = form.cleaned_data['quantity_received']
            destination_location = form.cleaned_data['destination_location']
            lot_number = form.cleaned_data.get('lot_number')
            expiration_date = form.cleaned_data.get('expiration_date')
            
            if quantity_received > transfer_request.quantity_transferred:
                messages.error(request, "Received quantity cannot exceed transferred quantity.")
                return redirect('purchase:stock_transfer_detail', pk=pk)
            try:
                with transaction.atomic():
                    lot_serial_obj = None
                    if transfer_request.product.tracking_method in ['lot', 'serial'] and lot_number:
                        
                        dispatched_lot_cost = getattr(transfer_request.dispatched_lot, 'cost_price', None)

                        lot_serial_obj, created = LotSerialNumber.objects.get_or_create(
                            product=transfer_request.product,
                            lot_number=lot_number,
                            location=destination_location,
                            defaults={
                                'expiration_date': expiration_date, 
                                'quantity': 0, 
                                'cost_price': dispatched_lot_cost
                            }
                        )

                    StockService.change_stock(
                        product=transfer_request.product,
                        warehouse=transfer_request.destination_warehouse,
                        quantity_change=quantity_received,
                        transaction_type='transfer_in',
                        user=request.user,
                        content_object=transfer_request,
                        location=destination_location,
                        lot_serial=lot_serial_obj,
                        notes=f"Transfer IN for request #{transfer_request.pk}"
                    )
                    
                    transfer_request.status = 'received'
                    transfer_request.quantity_received = quantity_received
                    transfer_request.save()
                    messages.success(request, f"Stock transfer received successfully.")
            except (ValueError, ValidationError) as e:
                messages.error(request, str(e))
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f"{field}: {error}")

    return redirect('purchase:stock_transfer_detail', pk=pk)

@login_required
def get_lots_for_location_ajax(request):
    location_id = request.GET.get('location_id')
    product_id = request.GET.get('product_id')
    
    if not location_id or not product_id:
        return JsonResponse({'error': 'Location and Product ID are required.'}, status=400)
    
    lots = LotSerialNumber.objects.filter(
        location_id=location_id,
        product_id=product_id,
        quantity__gt=0
    ).values('id', 'lot_number', 'quantity', 'expiration_date')

    lots_data = []
    for lot in lots:
        exp_date_str = lot['expiration_date'].strftime('%d-%b-%Y') if lot['expiration_date'] else 'N/A'
        lots_data.append({
            'id': lot['id'],
            'text': f"Lot: {lot['lot_number']} (Qty: {lot['quantity']}, Exp: {exp_date_str})"
        })

    return JsonResponse({'lots': list(lots_data)})


@login_required
def create_purchase_return(request):
    user = request.user
    if not (user.is_superuser or user.groups.filter(name='Branch Manager').exists()):
        return redirect('dashboard')

    user_warehouse = getattr(user, 'warehouse', None)
    if not user.is_superuser and not user_warehouse:
        messages.error(request, "You are not assigned to any branch.")
        return redirect('dashboard')

    form_kwargs = {'warehouse': user_warehouse}
    
    if request.method == 'POST':
        form = PurchaseReturnForm(request.POST)
        formset = PurchaseReturnItemFormSet(request.POST, prefix='items', form_kwargs=form_kwargs)

        for item_form in formset:
            product_id = item_form.data.get(f"{item_form.prefix}-product")
            if product_id and user_warehouse:
                item_form.fields['lot_serial'].queryset = LotSerialNumber.objects.filter(
                    product_id=product_id,
                    location__warehouse=user_warehouse,
                    quantity__gt=0
                )

        if form.is_valid() and formset.is_valid():
            try:
                with transaction.atomic():
                    purchase_return = form.save(commit=False)
                    purchase_return.user = user
                    purchase_return.warehouse = user_warehouse
                    purchase_return.status = 'pending_approval'
                    purchase_return.save()

                    items_to_create = []
                    for item_form_data in formset.cleaned_data:
                        if item_form_data and not item_form_data.get('DELETE', False):
                            product = item_form_data['product']
                            lot = item_form_data['lot_serial']
                            quantity = item_form_data['quantity']
                            unit_price = Decimal(0)

                            if lot and lot.cost_price is not None:
                                unit_price = lot.cost_price
                            
                            else:
                                product_supplier = ProductSupplier.objects.filter(
                                    product=product,
                                    supplier=purchase_return.supplier
                                ).first()
                                
                                if product_supplier and product_supplier.price > 0:
                                    unit_price = product_supplier.price
                                else:
                                    unit_price = product.cost_price or Decimal(0)

                            items_to_create.append(
                                PurchaseReturnItem(
                                    purchase_return=purchase_return, 
                                    product=product,
                                    quantity=quantity, 
                                    lot_serial=lot, 
                                    unit_price=unit_price
                                )
                            )
                    
                    PurchaseReturnItem.objects.bulk_create(items_to_create)
                    messages.success(request, "Purchase Return Request has been submitted for approval.")
                    return redirect('purchase:purchase_return_list')

            except Exception as e:
                messages.error(request, f"An error occurred: {e}")
    else:
        form = PurchaseReturnForm()
        formset = PurchaseReturnItemFormSet(prefix='items', queryset=PurchaseReturnItem.objects.none(), form_kwargs=form_kwargs)

    context = {
        'form': form,
        'formset': formset,
        'title': 'Create Purchase Return Request'
    }
    return render(request, 'purchase/create_purchase_return.html', context)

@login_required
def get_lots_for_product_ajax(request):
    product_id = request.GET.get('product_id')
    user_warehouse = getattr(request.user, 'warehouse', None)

    lots_data = []
    if product_id and user_warehouse:
        lots = LotSerialNumber.objects.filter(
            product_id=product_id,
            location__warehouse=user_warehouse,
            quantity__gt=0
        ).order_by('created_at')
        
        for lot in lots:
            exp_date_str = lot.expiration_date.strftime('%d-%b-%Y') if lot.expiration_date else 'N/A'
            lots_data.append({
                'id': lot.id,
                'text': f"Lot: {lot.lot_number} (Qty: {lot.quantity}, Exp: {exp_date_str})"
            })

    return JsonResponse(lots_data, safe=False)

@login_required
def purchase_return_list(request):
    user = request.user
    
    if not (user.is_superuser or user.groups.filter(name='Branch Manager').exists()):
        return redirect('dashboard')

    if user.is_superuser:
        return_list = PurchaseReturn.objects.select_related('supplier', 'user', 'warehouse').all().order_by('-return_date')
    else:
        user_warehouse = getattr(user, 'warehouse', None)
        if user_warehouse:
            return_list = PurchaseReturn.objects.select_related('supplier', 'user', 'warehouse').filter(warehouse=user_warehouse).order_by('-return_date')
        else:
            return_list = PurchaseReturn.objects.none()

    context = {
        'return_list': return_list,
        'title': 'Purchase Returns'
    }
    return render(request, 'purchase/purchase_return_list.html', context)

@login_required
def purchase_return_detail(request, pk):
    user = request.user
    purchase_return = get_object_or_404(PurchaseReturn.objects.select_related('warehouse'), pk=pk)
    
    exchange_formset = None 
    form_kwargs = {'warehouse': purchase_return.warehouse}
    if purchase_return.status == 'waiting_replacement':
        initial_data = []
        for item in purchase_return.items.select_related('product'):
            initial_data.append({
                'purchase_return_item_id': item.id,
                'product_name': item.product.name,
                'quantity_to_receive': item.quantity,
                'product_tracking_method': item.product.tracking_method,
            })
        exchange_formset = ExchangeReceiveItemFormSet(initial=initial_data, prefix='exchange_items', form_kwargs=form_kwargs)
        for form in exchange_formset:
            form.fields['destination_location'].queryset = Location.objects.filter(warehouse=purchase_return.warehouse)

    if request.method == 'POST':
        if 'approve_return' in request.POST and user.is_superuser:
            purchase_return.status = 'approved'
            purchase_return.save()
            messages.success(request, f"Return #{purchase_return.pk} has been approved.")
            return redirect('purchase:purchase_return_detail', pk=purchase_return.pk)

        # Ship Action
        if 'ship_return' in request.POST:
            if purchase_return.status == 'approved':
                try:
                    # Settings Load
                    settings = FinanceSettings.objects.first()
                    if not settings:
                        raise Exception("Finance Settings not configured.")
                    
                    inventory_account = settings.default_inventory_account
                    exchange_account = getattr(settings, 'default_exchange_clearing_account', None)

                    # Validation
                    if not inventory_account:
                        raise Exception("Default Inventory Account is not set in settings.")
                    
                    if purchase_return.return_type == 'exchange' and not exchange_account:
                        raise Exception("Default 'Exchange Clearing Account' is not set in Finance Settings.")

                    with transaction.atomic():
                        # Stock Deduction
                        for item in purchase_return.items.all():
                            StockService.change_stock(
                                product=item.product,
                                warehouse=purchase_return.warehouse,
                                quantity_change=-item.quantity,
                                transaction_type='purchase_return',
                                user=request.user,
                                content_object=purchase_return,
                                lot_serial=item.lot_serial,
                                location=item.lot_serial.location if item.lot_serial else None,
                                notes=f"Shipped for Purchase Return #{purchase_return.pk} (Type: {purchase_return.get_return_type_display()})"
                            )
                        
                        # Financial Records
                        if purchase_return.return_type == 'credit':
                            create_financial_records_from_purchase_return(purchase_return, request.user)
                            purchase_return.status = 'shipped' 
                            purchase_return.save(update_fields=['status'])
                            messages.success(request, f"Return #{purchase_return.pk} (Credit) has been shipped. Financial entries posted.")
                        
                        elif purchase_return.return_type == 'exchange':
                            total_return_value = purchase_return.items.aggregate(
                                total=Sum(F('quantity') * F('unit_price'), output_field=DecimalField(max_digits=12, decimal_places=2))
                            )['total'] or Decimal(0)
                            
                            if total_return_value > 0:
                                create_journal_entry(
                                    date=timezone.now().date(),
                                    description=f"Stock-Out for Exchange PR #{purchase_return.pk}",
                                    debit_account=exchange_account,   # Debit: Goods Sent for Exchange (Asset)
                                    credit_account=inventory_account, # Credit: Inventory
                                    amount=total_return_value,
                                    user=user,
                                    warehouse=purchase_return.warehouse,
                                    content_object=purchase_return
                                )
                            
                            purchase_return.status = 'waiting_replacement'
                            purchase_return.save(update_fields=['status'])
                            messages.success(request, f"Return #{purchase_return.pk} (Exchange) has been shipped. Now waiting for replacement product.")
                            
                        return redirect('purchase:purchase_return_detail', pk=purchase_return.pk)
                except Exception as e:
                    messages.error(request, f"An error occurred: {e}")
            else:
                messages.warning(request, f"Return must be in 'Approved' state to be shipped.")

        if 'receive_exchange' in request.POST:
            exchange_formset = ExchangeReceiveItemFormSet(request.POST, prefix='exchange_items', form_kwargs=form_kwargs)
            
            for form in exchange_formset:
                form.fields['destination_location'].queryset = Location.objects.filter(warehouse=purchase_return.warehouse)
            
            if exchange_formset.is_valid():
                try:
                    settings = FinanceSettings.objects.first()
                    if not settings:
                        raise Exception("Finance Settings missing.")
                    
                    inventory_account = settings.default_inventory_account
                    exchange_account = getattr(settings, 'default_exchange_clearing_account', None)
                    
                    if not (inventory_account and exchange_account):
                         raise Exception("Inventory or Exchange Account missing in settings.")

                    with transaction.atomic():
                        total_return_value = Decimal(0)
                        
                        for form in exchange_formset:
                            data = form.cleaned_data
                            quantity_received = data.get('quantity_to_receive', 0)
                            
                            if quantity_received > 0:
                                return_item = get_object_or_404(PurchaseReturnItem, id=data['purchase_return_item_id'])
                                new_lot_number = data.get('lot_number')
                                
                                if return_item.product.tracking_method in ['lot', 'serial'] and new_lot_number:
                                    if LotSerialNumber.objects.filter(product=return_item.product, lot_number=new_lot_number).exists():
                                        raise ValidationError(f"Lot number '{new_lot_number}' already exists for this product.")
                                
                                StockService.add_stock(
                                    product=return_item.product,
                                    warehouse=purchase_return.warehouse,
                                    quantity=quantity_received,
                                    user=request.user,
                                    content_object=purchase_return,
                                    location=data['destination_location'], 
                                    lot_number=new_lot_number,
                                    expiration_date=data.get('expiration_date'), 
                                    cost_price=return_item.unit_price
                                )
                                total_return_value += (quantity_received * return_item.unit_price)

                                if new_lot_number:
                                    try:
                                        new_lot_obj = LotSerialNumber.objects.get(
                                            product=return_item.product, 
                                            lot_number=new_lot_number
                                        )
                                        return_item.received_lot_serial = new_lot_obj
                                        return_item.save(update_fields=['received_lot_serial'])
                                    except LotSerialNumber.DoesNotExist:
                                        pass

                        if total_return_value > 0:
                            create_journal_entry(
                                date=timezone.now().date(),
                                description=f"Stock-In for Exchange PR #{purchase_return.pk}",
                                debit_account=inventory_account, # Debit: Inventory (Stock Back)
                                credit_account=exchange_account, # Credit: Goods Sent for Exchange (Clearing)
                                amount=total_return_value,
                                user=user,
                                warehouse=purchase_return.warehouse,
                                content_object=purchase_return
                            )

                        purchase_return.status = 'completed'
                        purchase_return.save(update_fields=['status'])
                        messages.success(request, f"Exchange product for Return #{purchase_return.pk} has been received into stock.")
                        
                except (ValidationError, Exception) as e: 
                    messages.error(request, f"An error occurred while receiving exchange: {e}")
            else:
                messages.error(request, "Please correct the errors in the 'Receive Exchange' form below.")
            
            return redirect('purchase:purchase_return_detail', pk=purchase_return.pk)

    context = {
        'purchase_return': purchase_return,
        'exchange_formset': exchange_formset,
        'title': f'Purchase Return #{purchase_return.pk} Details'
    }
    return render(request, 'purchase/purchase_return_detail.html', context)

@login_required
@permission_required('purchase.view_purchasereturn', raise_exception=True)
def export_purchase_return_pdf(request, pk):
    purchase_return = get_object_or_404(PurchaseReturn.objects.select_related('supplier', 'warehouse', 'user'), pk=pk)
    
    show_price = request.user.is_superuser

    response = HttpResponse(content_type='application/pdf')
    filename = f"ReturnNote-PR-{purchase_return.pk}.pdf"
    response['Content-Disposition'] = f'attachment; filename="{filename}"'

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=30, leftMargin=30, topMargin=30, bottomMargin=30)
    story = []

    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name='TitleStyle', fontSize=20, fontName='Helvetica-Bold', alignment=TA_RIGHT, textColor=colors.HexColor("#4e73df")))
    styles.add(ParagraphStyle(name='HeaderStyle', fontSize=10, fontName='Helvetica-Bold'))
    styles.add(ParagraphStyle(name='NormalStyle', fontSize=10, fontName='Helvetica'))
    styles.add(ParagraphStyle(name='SignatureStyle', fontSize=10, fontName='Helvetica', alignment=TA_CENTER, paddingTop=20))

    logo_path = os.path.join(settings.STATICFILES_DIRS[0], 'images', 'logo.png')
    logo = Image(logo_path, width=1.5*inch, height=0.5*inch) if os.path.exists(logo_path) else Paragraph("NOVO", styles['HeaderStyle'])
    
    header_data = [[logo, Paragraph("Material Return Note", styles['TitleStyle'])]]
    header_table = Table(header_data, colWidths=[3*inch, 4.5*inch], style=[('VALIGN', (0,0), (-1,-1), 'TOP')])
    story.append(header_table)
    story.append(Spacer(1, 0.4*inch))

    info_data = [
        [Paragraph(f"<b>Return ID:</b> PR-{purchase_return.pk}", styles['NormalStyle']), Paragraph(f"<b>Return Date:</b> {purchase_return.return_date.strftime('%d %b, %Y')}", styles['NormalStyle'])],
        [Paragraph(f"<b>Branch:</b> {purchase_return.warehouse.name}", styles['NormalStyle']), Paragraph(f"<b>Status:</b> {purchase_return.get_status_display()}", styles['NormalStyle'])],
        [Paragraph(f"<b>Supplier:</b> {purchase_return.supplier.name}", styles['NormalStyle']), Paragraph(f"<b>Reason:</b> {purchase_return.get_return_reason_display()}", styles['NormalStyle'])],
    ]
    info_table = Table(info_data, colWidths=[3.75*inch, 3.75*inch])
    story.append(info_table)
    story.append(Spacer(1, 0.4*inch))

    items_data = []
    grand_total = 0

    if show_price:
        items_header = [Paragraph(h, styles['HeaderStyle']) for h in ['Product', 'Lot/Serial', 'Qty', 'Cost Price', 'Total Cost']]
        col_widths = [2.5*inch, 2*inch, 0.7*inch, 1.1*inch, 1.2*inch]
    else:
        items_header = [Paragraph(h, styles['HeaderStyle']) for h in ['Product', 'Lot/Serial', 'Qty', 'Expiration Date']]
        col_widths = [3*inch, 2*inch, 0.7*inch, 1.8*inch]
        
    items_data.append(items_header)

    for item in purchase_return.items.all():
        if show_price:
            items_data.append([
                item.product.name,
                item.lot_serial.lot_number if item.lot_serial else 'N/A',
                item.quantity,
                f"{item.unit_price:,.2f}",
                f"{item.total_cost:,.2f}"
            ])
            grand_total += item.total_cost
        else:
            exp_date = item.lot_serial.expiration_date.strftime('%d %b, %Y') if item.lot_serial and item.lot_serial.expiration_date else 'N/A'
            items_data.append([
                item.product.name,
                item.lot_serial.lot_number if item.lot_serial else 'N/A',
                item.quantity,
                exp_date
            ])

    if show_price:
        items_data.append(['', '', '', Paragraph("<b>Grand Total</b>", styles['HeaderStyle']), Paragraph(f"<b>{grand_total:,.2f}</b>", styles['NormalStyle'])])
    
    items_table = Table(items_data, colWidths=col_widths)
    items_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor("#eaecf4")),
        ('GRID', (0,0), (-1,-1), 1, colors.grey),
        ('ALIGN', (2,1), (-1,-1), 'RIGHT'),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
    ]))
    story.append(items_table)
    story.append(Spacer(1, 1.5*inch))

    signature_data = [
        [Paragraph('--------------------<br/>Prepared By', styles['SignatureStyle']),
         Paragraph('--------------------<br/>Approved By', styles['SignatureStyle']),
         Paragraph('--------------------<br/>Received By', styles['SignatureStyle'])]
    ]
    signature_table = Table(signature_data, colWidths=[2.5*inch, 2.5*inch, 2.5*inch], hAlign='CENTER')
    story.append(signature_table)

    doc.build(story)
    
    buffer.seek(0)
    response.write(buffer.getvalue())
    return response