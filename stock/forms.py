# stock/forms.py

from django import forms
from django.db.models import Q
from .models import Warehouse, Location, LotSerialNumber, InventoryTransaction
from products.models import Product
from django.contrib.auth import get_user_model

User = get_user_model()

class WarehouseForm(forms.ModelForm):
    class Meta:
        model = Warehouse
        fields = ['name', 'address']
        labels = {'name': 'Warehouse Name', 'address': 'Address'}
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Enter warehouse name'}),
            'address': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Enter warehouse address'}),
        }

class LocationForm(forms.ModelForm):
    class Meta:
        model = Location
        fields = ['name', 'warehouse', 'parent_location', 'description']
        labels = {
            'name': 'Location Name', 'warehouse': 'Warehouse',
            'parent_location': 'Parent Location', 'description': 'Description',
        }
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Enter location name (e.g., Aisle 1, Shelf B)'}),
            'warehouse': forms.Select(attrs={'class': 'form-control'}),
            'parent_location': forms.Select(attrs={'class': 'form-control'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Enter location description'}),
        }

class LotSerialNumberForm(forms.ModelForm):
    class Meta:
        model = LotSerialNumber
        fields = ['product', 'location', 'lot_number', 'quantity', 'expiration_date']
        widgets = {
            'product': forms.Select(attrs={'class': 'form-control'}),
            'location': forms.Select(attrs={'class': 'form-control'}),
            'lot_number': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g., BN12345 or SER98765'}),
            'quantity': forms.NumberInput(attrs={'class': 'form-control'}),
            'expiration_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # শুধুমাত্র যে প্রোডাক্টগুলো লট বা সিরিয়াল দিয়ে ট্র্যাক করা হয়, সেগুলোই দেখানো হবে
        self.fields['product'].queryset = Product.objects.filter(
            Q(tracking_method='lot') | Q(tracking_method='serial') # <-- 'models.Q' থেকে 'Q' করা হয়েছে
        ).order_by('name')

class InventoryTransactionForm(forms.ModelForm):
    new_lot_number = forms.CharField(
        label="New Lot/Batch Number",
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Enter new lot/serial number'})
    )
    new_lot_expiration_date = forms.DateField(
        label="Expiration Date for New Lot",
        required=False,
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'})
    )

    class Meta:
        model = InventoryTransaction
        fields = ['product', 'transaction_type', 'quantity', 'lot_serial', 'customer', 'supplier', 
                  'source_location', 'destination_location', 'notes']
        labels = {
            'lot_serial': 'Select Existing Lot/Serial (for Sales/Transfers)',
            'customer': 'Customer (for Sales)', 'supplier': 'Supplier (for Receipts)',
            'source_location': 'Source Location (for Sale/Transfer)',
            'destination_location': 'Destination Location (for Receipt/Transfer)',
        }
        
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['lot_serial'].required = False
        self.fields['lot_serial'].queryset = LotSerialNumber.objects.none()
        
# --- নতুন LotBasedInventoryAdjustmentForm ---

class LotBasedInventoryAdjustmentForm(forms.Form):
    warehouse = forms.ModelChoiceField(
        queryset=Warehouse.objects.all().order_by('name'),
        label="Select Branch",
        widget=forms.Select(attrs={
            'class': 'form-select select2-field',
            'id': 'id_warehouse',
            'data-placeholder': 'Search and select a branch' # placeholder যোগ করা হয়েছে
        })
    )
    product = forms.ModelChoiceField(
        queryset=Product.objects.none(),
        label="Select Product",
        widget=forms.Select(attrs={
            'class': 'form-select select2-field',
            'id': 'id_product',
            'data-placeholder': 'First select a branch' # placeholder যোগ করা হয়েছে
        })
    )
    lot = forms.ModelChoiceField(
        queryset=LotSerialNumber.objects.none(),
        label="Select Lot/Batch",
        widget=forms.Select(attrs={
            'class': 'form-select select2-field',
            'id': 'id_lot',
            'data-placeholder': 'First select a product' # placeholder যোগ করা হয়েছে
        })
    )
    new_quantity = forms.DecimalField(
        min_value=0,
        label="New Counted Quantity",
        widget=forms.NumberInput(attrs={'class': 'form-control', 'id': 'id_new_quantity', 'placeholder': 'Enter the actual quantity'}),
        help_text="Enter the actual quantity found in the physical count for this lot."
    )

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)

        if user and not user.is_superuser:
            user_warehouse = getattr(user, 'warehouse', None)
            if user_warehouse:
                self.fields['warehouse'].queryset = Warehouse.objects.filter(pk=user_warehouse.pk)

        if 'warehouse' in self.data:
            try:
                warehouse_id = int(self.data.get('warehouse'))
                self.fields['product'].queryset = Product.objects.filter(
                    lots__location__warehouse_id=warehouse_id, 
                    lots__quantity__gt=0
                ).distinct().order_by('name')
            except (ValueError, TypeError):
                pass
        
        if 'product' in self.data:
            try:
                product_id = int(self.data.get('product'))
                warehouse_id = int(self.data.get('warehouse'))
                self.fields['lot'].queryset = LotSerialNumber.objects.filter(
                    product_id=product_id, 
                    location__warehouse_id=warehouse_id,
                ).order_by('-created_at')
            except (ValueError, TypeError):
                pass

# --- আপনার পুরনো TransactionFilterForm অপরিবর্তিত আছে ---

class DateRangeForm(forms.Form):
    start_date = forms.DateField(widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}), required=False)
    end_date = forms.DateField(widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}), required=False)

class StockMovementFilterForm(forms.Form):
    product = forms.ModelChoiceField(
        queryset=Product.objects.all(),
        required=False,
        widget=forms.Select(attrs={'class': 'form-control select2'})
    )
    transaction_type = forms.ChoiceField(
        choices=[('', 'All Types')] + [
            ('purchase', 'Purchase'),
            ('sale', 'Sale'),
            ('adjustment_in', 'Adjustment In'),
            ('adjustment_out', 'Adjustment Out'),
            ('transfer_in', 'Transfer In'),
            ('transfer_out', 'Transfer Out'),
        ],
        required=False,
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    start_date = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'})
    )
    end_date = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'})
    )
    warehouse = forms.ModelChoiceField(
        queryset=Warehouse.objects.all(),
        required=False,
        widget=forms.Select(attrs={'class': 'form-control'})
    )

class TransactionFilterForm(forms.Form):
    start_date = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={'type': 'date', 'class': 'form-control'})
    )
    end_date = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={'type': 'date', 'class': 'form-control'})
    )
    user = forms.ModelChoiceField(
        queryset=get_user_model().objects.all(),
        required=False,
        widget=forms.Select(attrs={'class': 'form-select select2'})
    )
    warehouse = forms.ModelChoiceField(
        queryset=Warehouse.objects.all(),
        required=False,
        label="Branch",
        widget=forms.Select(attrs={'class': 'form-select select2'})
    )

    def __init__(self, *args, **kwargs):
        # ব্যবহারকারীর ভূমিকার উপর ভিত্তি করে ফর্মের ফিল্ড পরিবর্তন করার জন্য
        request_user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)

        if request_user and not request_user.is_superuser:
            user_warehouse = getattr(request_user, 'warehouse', None)
            if user_warehouse:
                # ব্রাঞ্চ ম্যানেজারের জন্য শুধুমাত্র তার ব্রাঞ্চের ইউজারদের দেখানো হবে
                self.fields['user'].queryset = User.objects.filter(warehouse=user_warehouse)
                # ব্রাঞ্চ ম্যানেজারের জন্য ওয়্যারহাউস ফিল্ডটি দেখানো হবে না
                del self.fields['warehouse']

#--- নতুন LotFilterForm ---
class LotFilterForm(forms.Form):
    product = forms.ModelChoiceField(
        queryset=Product.objects.all(),
        required=False,
        label="Filter by Product",
        widget=forms.Select(attrs={'class': 'form-control select2'})
    )
    warehouse = forms.ModelChoiceField(
        queryset=Warehouse.objects.all().order_by('name'),
        required=False,
        label="Filter by Branch",
        widget=forms.Select(attrs={'class': 'form-control select2'})
    )

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)

        # ব্রাঞ্চ ম্যানেজারের জন্য শুধুমাত্র তার ব্রাঞ্চের প্রোডাক্টগুলো দেখানো হবে
        if user and not user.is_superuser:
            user_warehouse = getattr(user, 'warehouse', None)
            if user_warehouse:
                # যে প্রোডাক্টগুলো এই ব্রাঞ্চের কোনো লটে আছে, শুধু সেগুলোই দেখানো হবে
                self.fields['product'].queryset = Product.objects.filter(
                    lots__location__warehouse=user_warehouse
                ).distinct().order_by('name')
            else:
                self.fields['product'].queryset = Product.objects.none()

            # ব্রাঞ্চ ম্যানেজারের জন্য ব্রাঞ্চ ফিল্টারটি লুকিয়ে রাখা হলো
            del self.fields['warehouse']