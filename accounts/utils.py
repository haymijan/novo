import requests
import logging
from django.conf import settings

logger = logging.getLogger(__name__)

def send_ooredoo_sms(phone, otp):

    if not str(phone).startswith('974'):
        phone = f"974{phone}"

    url = settings.OOREDOO_SMS_URL
    params = {
        'customerID': settings.OOREDOO_CUSTOMER_ID,
        'userName': settings.OOREDOO_USERNAME,
        'userPassword': settings.OOREDOO_PASSWORD,
        'originator': settings.OOREDOO_ORIGINATOR,
        'smsText': f"Your Login OTP is: {otp}. Valid for 5 minutes.",
        'recipientPhone': phone,
        'messageType': 'Latin',
        'defDate': '',
        'blink': 'false',
        'flash': 'false',
        'Private': 'false',
    }

    try:
        response = requests.get(url, params=params)
        if response.status_code == 200 and '<TransactionID>' in response.text:
            return True
        else:
            logger.error(f"Ooredoo SMS Failed: {response.text}")
            return False
    except Exception as e:
        logger.error(f"SMS Connection Error: {str(e)}")
        return False