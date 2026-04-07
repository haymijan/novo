from django import forms
from django.forms import inlineformset_factory, formset_factory
from .models import SalesOrder, SalesOrderItem, SalesReturn, SalesReturnItem
from partners.models import Customer
from stock.models import Location, LotSerialNumber, Warehouse, Stock
from products.models import Product
from django.contrib.auth import get_user_model

from finance.banking.models import PaymentMethod
#from banking.models import PaymentMethod

User = get_user_model()

class SalesOrderForm(forms.ModelForm):
    make_payment = forms.BooleanField(
        required=False, 
        label="Receive Payment Now?", 
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input', 'id': 'chk_make_payment'})
    )
    
    payment_method = forms.ModelChoiceField(
        queryset=PaymentMethod.objects.filter(is_active=True),
        required=False,
        label="Payment Method",
        empty_label="Select Payment Method",
        widget=forms.Select(attrs={'class': 'form-select', 'id': 'select_payment_method'})
    )
    
    amount_received = forms.DecimalField(
        required=False,
        max_digits=12,
        decimal_places=2,
        label="Amount Received",
        widget=forms.NumberInput(attrs={'class': 'form-control', 'placeholder': '0.00'})
    )
    
    payment_reference = forms.CharField(
        required=False,
        label="Reference / Gift Card Code",
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Card Code / Cheque No'})
    )

    discount = forms.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        initial=0.00, 
        widget=forms.NumberInput(attrs={'class': 'form-control text-end', 'step': '0.01'})
    )

    round_off_amount = forms.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        initial=0.00,
        required=False,
        widget=forms.NumberInput(attrs={'class': 'form-control text-end', 'step': '0.01'})
    )

    tax_amount = forms.DecimalField(
        max_digits=10, decimal_places=2, initial=0.00, required=False,
        widget=forms.NumberInput(attrs={'class': 'form-control text-end', 'step': '0.01'})
    )
    shipping_cost = forms.DecimalField(
        max_digits=10, decimal_places=2, initial=0.00, required=False,
        widget=forms.NumberInput(attrs={'class': 'form-control text-end', 'step': '0.01'})
    )

    class Meta:
        model = SalesOrder
        fields = [
            'customer', 'order_date', 'expected_delivery_date', 
            'status', 'notes', 'warehouse', 
            'discount', 'tax_amount', 'shipping_cost', 'round_off_amount' 
        ]
        widgets = {
            'customer': forms.Select(attrs={'class': 'form-control select2'}),
            'order_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'expected_delivery_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'status': forms.Select(attrs={'class': 'form-control'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
            'warehouse': forms.Select(attrs={'class': 'form-control select2'}),
        }

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)

        if user:
            if user.is_superuser:
                self.fields['warehouse'].queryset = Warehouse.objects.all()
            else:
                user_warehouse = getattr(user, 'warehouse', None)
                if user_warehouse:
                    self.fields['warehouse'].queryset = Warehouse.objects.filter(id=user_warehouse.id)
                    if not self.instance.pk:
                        self.initial['warehouse'] = user_warehouse
                        self.fields['warehouse'].initial = user_warehouse
                    self.fields['warehouse'].empty_label = None 
                else:
                    self.fields['warehouse'].queryset = Warehouse.objects.none()

    def clean(self):
        cleaned_data = super().clean()
        make_payment = cleaned_data.get('make_payment')
        payment_method = cleaned_data.get('payment_method')
        amount_received = cleaned_data.get('amount_received')
        reference = cleaned_data.get('payment_reference')

        if make_payment:
            if not payment_method:
                self.add_error('payment_method', 'Please select a payment method.')
            if not amount_received or amount_received <= 0:
                self.add_error('amount_received', 'Please enter a valid amount.')

            if payment_method and payment_method.type == 'Gift Card' and not reference:
                self.add_error('payment_reference', 'Please enter the Gift Card Code.')
        
        return cleaned_data

class SalesOrderItemForm(forms.ModelForm):
    class Meta:
        model = SalesOrderItem
        fields = ['product', 'quantity', 'unit_price']
        widgets = {
            'product': forms.Select(attrs={'class': 'form-control product-select'}),
            'quantity': forms.NumberInput(attrs={'class': 'form-control quantity-input text-center', 'min': '1'}),
            'unit_price': forms.NumberInput(attrs={'class': 'form-control unit-price-input text-end'}),
        }

    def __init__(self, *args, **kwargs):
        user_warehouse = kwargs.pop('warehouse', None)
        kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        
        products_qs = Product.objects.filter(is_active=True)
        if user_warehouse:
            products_in_warehouse = Stock.objects.filter(
                warehouse=user_warehouse, 
                quantity__gt=0
            ).values_list('product_id', flat=True)
            products_qs = products_qs.filter(id__in=products_in_warehouse)
        
        self.fields['product'].queryset = products_qs.distinct().order_by('name')

SalesOrderItemFormSet = inlineformset_factory(
    SalesOrder, SalesOrderItem, form=SalesOrderItemForm,
    fields=['product', 'quantity', 'unit_price'], extra=1, can_delete=True
)

class SalesOrderItemFulfillmentForm(forms.Form):
    sales_order_item_id = forms.IntegerField(widget=forms.HiddenInput())
    quantity_fulfilled = forms.IntegerField(min_value=0, label="Fulfill Quantity", widget=forms.NumberInput(attrs={'class': 'form-control'}))
    source_location = forms.ModelChoiceField(queryset=Location.objects.none(), label="Source Location", widget=forms.Select(attrs={'class': 'form-control'}))
    lot_serial = forms.ModelChoiceField(queryset=LotSerialNumber.objects.none(), required=False, label="Lot/Serial", widget=forms.Select(attrs={'class': 'form-control'}))

SalesOrderItemFulfillmentFormSet = formset_factory(SalesOrderItemFulfillmentForm, extra=0)

class SalesOrderFilterForm(forms.Form):
    start_date = forms.DateField(required=False, widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}), label="Start Date")
    end_date = forms.DateField(required=False, widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}), label="End Date")
    order_number = forms.CharField(required=False, widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Order #'}), label="Order Number")
    user = forms.ModelChoiceField(queryset=User.objects.all(), required=False, widget=forms.Select(attrs={'class': 'form-control select2'}), label="User")
    warehouse = forms.ModelChoiceField(queryset=Warehouse.objects.all(), required=False, widget=forms.Select(attrs={'class': 'form-control select2'}), label="Branch")

    def __init__(self, *args, **kwargs):
        request_user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)

        if request_user and not request_user.is_superuser:
            user_warehouse = getattr(request_user, 'warehouse', None)
            if user_warehouse:
                self.fields['warehouse'].queryset = Warehouse.objects.filter(id=user_warehouse.id)
                self.fields['warehouse'].initial = user_warehouse
            else:
                self.fields['warehouse'].queryset = Warehouse.objects.none()

class FindSalesOrderForm(forms.Form):
    order_id = forms.IntegerField(
        label="Enter Sales Order ID (e.g., 13)",
        widget=forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Enter SO Number'})
    )

class SalesReturnForm(forms.ModelForm):
    class Meta:
        model = SalesReturn
        fields = ['reason']
        widgets = {
            'reason': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }

class SalesReturnItemForm(forms.ModelForm):
    original_quantity = forms.IntegerField(disabled=True, required=False)

    class Meta:
        model = SalesReturnItem
        fields = ['product', 'quantity', 'lot_sold_from']
        widgets = {
            'product': forms.HiddenInput(),
            'lot_sold_from': forms.HiddenInput(),
            'quantity': forms.NumberInput(attrs={'class': 'form-control form-control-sm', 'min': '0'}),
        }
    
    def __init__(self, *args, **kwargs):
        self.sales_order_item = kwargs.pop('sales_order_item', None)
        super().__init__(*args, **kwargs)

        if self.sales_order_item:
            self.fields['original_quantity'].initial = self.sales_order_item.quantity
            self.fields['quantity'].widget.attrs['max'] = self.sales_order_item.quantity

SalesReturnItemFormSet = inlineformset_factory(
    SalesReturn,
    SalesReturnItem,
    form=SalesReturnItemForm,
    extra=0,
    can_delete=False,
    fields=['product', 'quantity', 'lot_sold_from']
)