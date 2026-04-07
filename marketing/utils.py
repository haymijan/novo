# marketing/utils.py

from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from django.conf import settings
import barcode
from barcode.writer import ImageWriter
from io import BytesIO
from email.mime.image import MIMEImage

def send_gift_card_email(gift_card):
    """
    এই ফাংশনটি একটি GiftCard অবজেক্ট গ্রহণ করে এবং কাস্টমারকে ইমেইল পাঠায়।
    """
    if not gift_card.customer or not gift_card.customer.email:
        print(f"Skipping email: No customer or email for card {gift_card.code}")
        return False

    # ১. বারকোড জেনারেট করা
    try:
        buffer = BytesIO()
        Code128 = barcode.get_barcode_class('code128')
        barcode_obj = Code128(gift_card.code, writer=ImageWriter())
        
        options = {
            'module_width': 0.4,
            'module_height': 15,
            'quiet_zone': 3,
            'write_text': False,
            'background': 'white'
        }
        barcode_obj.write(buffer, options=options)
        buffer.seek(0)
        image_data = buffer.getvalue()
    except Exception as e:
        print(f"Barcode Error: {e}")
        image_data = None

    # ২. ইমেইল তৈরি
    context = {
        'card': gift_card,
        'company_name': 'NOVO ERP', # আপনার কোম্পানির নাম দিন
    }
    
    # টেম্পলেট লোড
    html_content = render_to_string('marketing/email_gift_card.html', context)
    text_content = strip_tags(html_content)
    subject = f"You've received a Gift Card - {gift_card.initial_value} TK"

    try:
        email = EmailMultiAlternatives(
            subject, 
            text_content, 
            settings.EMAIL_HOST_USER,
            [gift_card.customer.email]
        )
        email.attach_alternative(html_content, "text/html")

        if image_data:
            image = MIMEImage(image_data)
            image.add_header('Content-ID', '<barcode_image>')
            image.add_header('Content-Disposition', 'inline', filename='barcode.png')
            email.attach(image)

        email.send()
        print(f"Email sent successfully to {gift_card.customer.email}")
        return True
        
    except Exception as e:
        print(f"Email Sending Failed: {e}")
        return False