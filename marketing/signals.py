# marketing/signals.py

from django.db.models.signals import post_save
from django.dispatch import receiver
from pos.models import POSOrder 
from marketing.models import GiftCard
from marketing.utils import send_gift_card_email
from products.models import Product 
import uuid

@receiver(post_save, sender=POSOrder)
def generate_gift_cards_on_sale(sender, instance, created, **kwargs):
    """
    POS অর্ডার যখন 'paid' হবে, তখন গিফট কার্ড জেনারেট হবে।
    """
    # ১. স্ট্যাটাস চেক (এখন মডেলে status ফিল্ড আছে তাই এটি কাজ করবে)
    if instance.status == 'paid': 
        
        # ২. আইটেম লুপ করা (lines এর বদলে items হবে)
        # আপনার মডেলে related_name='items' দেওয়া আছে
        for line in instance.items.all(): 
            
            product = line.product
            
            # ৩. প্রোডাক্ট টাইপ চেক
            # (নিশ্চিত হতে হবে Product মডেলে product_type আছে, যা আমরা আগে যোগ করেছি)
            if hasattr(product, 'product_type') and product.product_type == 'gift_card':
                
                # কার্ডের ভ্যালু বের করা
                card_value = product.gift_card_value
                
                # ৪. প্রাইস চেক (price এর বদলে unit_price হবে)
                # POSOrderItem মডেলে ফিল্ডের নাম unit_price
                if card_value <= 0:
                    card_value = line.unit_price 
                
                qty = int(line.quantity)
                
                for _ in range(qty):
                    unique_code = str(uuid.uuid4()).split('-')[0].upper() + str(uuid.uuid4()).split('-')[1].upper()
                    
                    new_card = GiftCard.objects.create(
                        code=unique_code,
                        customer=instance.customer,
                        initial_value=card_value,
                        current_balance=card_value,
                        is_active=True
                    )
                    
                    if instance.customer and instance.customer.email:
                        send_gift_card_email(new_card)
                        
                    print(f"Generated Gift Card: {new_card.code} for Order #{instance.id}")