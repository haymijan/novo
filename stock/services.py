# stock/services.py

from django.db import transaction
from django.db.models import F
from .models import Stock, InventoryTransaction, Location, LotSerialNumber, Warehouse
from decimal import Decimal

class StockService:
    @staticmethod
    def change_stock(product, warehouse, quantity_change, transaction_type, user, 
                     content_object=None, location=None, lot_serial=None, notes='', 
                     from_warehouse=None, to_warehouse=None):
        
        if content_object and getattr(content_object, 'skip_stock_update', False):
            return

        if quantity_change == 0:
            return

        with transaction.atomic():
            stock, created = Stock.objects.select_for_update().get_or_create(
                product=product,
                warehouse=warehouse,
                defaults={'quantity': 0}
            )

            if quantity_change < 0 and stock.quantity < abs(quantity_change):
                raise ValueError(f"'{product.name}' এর পর্যাপ্ত স্টক '{warehouse.name}'-এ নেই।")

            stock.quantity = F('quantity') + quantity_change
            stock.save(update_fields=['quantity'])

            if lot_serial:
                lot = LotSerialNumber.objects.select_for_update().get(id=lot_serial.id)
                if quantity_change < 0 and lot.quantity < abs(quantity_change):
                    raise ValueError(f"'{lot.lot_number}' লটে পর্যাপ্ত স্টক নেই।")
                
                lot.quantity = F('quantity') + quantity_change
                lot.save(update_fields=['quantity'])

            source_loc = None
            dest_loc = None
            
            if content_object:
                if transaction_type == 'transfer_out' and hasattr(content_object, 'destination_warehouse'):
                     source_loc = location
                     if hasattr(content_object, 'destination_warehouse'):
                        dest_loc = content_object.destination_warehouse.locations.first()
                elif transaction_type == 'transfer_in' and hasattr(content_object, 'source_warehouse'):
                     if hasattr(content_object, 'dispatched_lot') and content_object.dispatched_lot:
                         source_loc = content_object.dispatched_lot.location
                     elif hasattr(content_object, 'source_warehouse'):
                         source_loc = content_object.source_warehouse.locations.first()
                     dest_loc = location
            
            if not source_loc and not dest_loc:
                if quantity_change > 0:
                    dest_loc = location
                else:
                    source_loc = location

            InventoryTransaction.objects.create(
                product=product,
                warehouse=warehouse,
                quantity=quantity_change,
                transaction_type=transaction_type,
                user=user,
                content_object=content_object,
                source_location=source_loc,
                destination_location=dest_loc,
                lot_serial=lot_serial,
                notes=notes,
                from_warehouse=from_warehouse,
                to_warehouse=to_warehouse
            )

    @staticmethod
    def adjust_stock_for_lot(lot_serial: LotSerialNumber, new_quantity: Decimal, user, notes: str):
        with transaction.atomic():
            locked_lot = LotSerialNumber.objects.select_for_update().get(pk=lot_serial.pk)
            current_quantity = locked_lot.quantity
            adjustment_quantity = Decimal(new_quantity) - current_quantity

            if adjustment_quantity == 0:
                return 

            StockService.change_stock(
                product=locked_lot.product,
                warehouse=locked_lot.location.warehouse,
                quantity_change=adjustment_quantity,
                transaction_type='adjustment',
                user=user,
                location=locked_lot.location,
                lot_serial=locked_lot,
                notes=notes or f"Adjusted from {current_quantity} to {new_quantity}"
            )

    @staticmethod
    def deduct_stock(product, warehouse, quantity_to_deduct, transaction_type, related_object, user, lot_serial=None):
        if not lot_serial:
            raise ValueError("Lot/Serial number must be specified for stock deduction.")
        
        StockService.change_stock(
            product=product,
            warehouse=warehouse,
            quantity_change=-Decimal(quantity_to_deduct),
            transaction_type=transaction_type,
            user=user,
            content_object=related_object,
            location=lot_serial.location,
            lot_serial=lot_serial,
            notes=f"Deducted for {transaction_type}"
        )
    
    @staticmethod
    def add_stock(product, warehouse, quantity, user, content_object=None, location=None, 
                  lot_number=None, expiration_date=None, cost_price=None, purchase_order_item=None):
        if quantity <= 0:
            raise ValueError("Quantity to add must be positive.")
        if not location:
            raise ValueError("Location must be specified to add stock.")
        if location.warehouse != warehouse:
            raise ValueError("The provided location does not belong to the specified warehouse.")

        with transaction.atomic():
            lot_serial = None
            if product.tracking_method in ['lot', 'serial']:
                if not lot_number:
                    raise ValueError("Lot number is required for tracked products.")
                
                lot_serial, created = LotSerialNumber.objects.get_or_create(
                    product=product,
                    location=location,
                    lot_number=lot_number,
                    defaults={
                        'quantity': 0,
                        'expiration_date': expiration_date,
                        'cost_price': cost_price,
                        'purchase_order_item': purchase_order_item
                    }
                )

                if not created and not lot_serial.purchase_order_item and purchase_order_item:
                    lot_serial.purchase_order_item = purchase_order_item
                    lot_serial.save(update_fields=['purchase_order_item'])

            StockService.change_stock(
                product=product,
                warehouse=warehouse,
                quantity_change=Decimal(quantity),
                transaction_type='purchase',
                user=user,
                content_object=content_object,
                location=location,
                lot_serial=lot_serial,
                notes=f"Received for PO-{content_object.pk}" if content_object else "Stock added"
            )

            if purchase_order_item:
                po_item = purchase_order_item
                po_item.quantity_received = F('quantity_received') + Decimal(quantity)
                po_item.save(update_fields=['quantity_received'])