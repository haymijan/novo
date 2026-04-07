from django.test import TestCase, Client, override_settings
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.core import mail
from django.core.cache import cache
from unittest.mock import patch, MagicMock
from decimal import Decimal

from stock.models import Warehouse
from .models import User, CustomUserManager
from .forms import PhoneLoginForm, OTPVerificationForm
from .utils import send_ooredoo_sms

User = get_user_model()

# Mock settings for Ooredoo SMS to prevent actual API calls during tests
@override_settings(
    OOREDOO_SMS_URL='http://mock-ooredoo-sms.com',
    OOREDOO_CUSTOMER_ID='test_id',
    OOREDOO_USERNAME='test_user',
    OOREDOO_PASSWORD='test_password',
    OOREDOO_ORIGINATOR='TestSender',
    AUTHENTICATION_BACKENDS=('django.contrib.auth.backends.ModelBackend',)
)
class AccountModelTest(TestCase):

    def setUp(self):
        self.warehouse = Warehouse.objects.create(name="Test Warehouse")

    def test_create_user(self):
        user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='password123',
            phone='1234567890',
            warehouse=self.warehouse
        )
        self.assertIsInstance(user, User)
        self.assertTrue(user.is_active)
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertEqual(user.email, 'test@example.com')
        self.assertEqual(user.username, 'testuser')
        self.assertEqual(user.phone, '1234567890')
        self.assertEqual(user.warehouse, self.warehouse)
        self.assertTrue(user.check_password('password123'))
        self.assertEqual(user.max_discount_percentage, Decimal('0.00'))

    def test_create_superuser(self):
        superuser = User.objects.create_superuser(
            username='adminuser',
            email='admin@example.com',
            password='adminpassword',
            phone='0987654321'
        )
        self.assertIsInstance(superuser, User)
        self.assertTrue(superuser.is_active)
        self.assertTrue(superuser.is_staff)
        self.assertTrue(superuser.is_superuser)
        self.assertEqual(superuser.email, 'admin@example.com')
        self.assertEqual(superuser.username, 'adminuser')
        self.assertEqual(superuser.phone, '0987654321')
        self.assertTrue(superuser.check_password('adminpassword'))

    def test_create_user_no_email(self):
        with self.assertRaisesMessage(ValueError, 'The Email field must be set'):
            User.objects.create_user(username='noemail', email='', password='password123')

    def test_user_str_method(self):
        user = User.objects.create_user(
            username='strtest',
            email='str@example.com',
            password='password123'
        )
        self.assertEqual(str(user), 'strtest')

    def test_user_max_discount_percentage_default(self):
        user = User.objects.create_user(
            username='discountuser',
            email='discount@example.com',
            password='password123'
        )
        self.assertEqual(user.max_discount_percentage, Decimal('0.00'))

    def test_user_max_discount_percentage_custom(self):
        user = User.objects.create_user(
            username='customdiscount',
            email='custom@example.com',
            password='password123',
            max_discount_percentage=Decimal('15.50')
        )
        self.assertEqual(user.max_discount_percentage, Decimal('15.50'))


@override_settings(
    OOREDOO_SMS_URL='http://mock-ooredoo-sms.com',
    OOREDOO_CUSTOMER_ID='test_id',
    OOREDOO_USERNAME='test_user',
    OOREDOO_PASSWORD='test_password',
    OOREDOO_ORIGINATOR='TestSender',
    AUTHENTICATION_BACKENDS=('django.contrib.auth.backends.ModelBackend',)
)
class AccountFormTest(TestCase):

    def setUp(self):
        self.warehouse = Warehouse.objects.create(name="Test Warehouse")
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='password123',
            phone='1234567890',
            warehouse=self.warehouse
        )

    def test_phone_login_form_valid(self):
        form = PhoneLoginForm(data={'phone': '1234567890'})
        self.assertTrue(form.is_valid())

    def test_phone_login_form_invalid_unregistered_phone(self):
        form = PhoneLoginForm(data={'phone': '9999999999'})
        self.assertFalse(form.is_valid())
        self.assertIn('This phone number is not registered.', form.errors['phone'])

    def test_otp_verification_form_valid(self):
        form = OTPVerificationForm(data={'otp': '1234'})
        self.assertTrue(form.is_valid())

    def test_otp_verification_form_invalid_short_otp(self):
        form = OTPVerificationForm(data={'otp': '123'})
        self.assertFalse(form.is_valid())
        self.assertIn('Ensure this value has at least 4 characters (it has 3).', form.errors['otp'])

    def test_otp_verification_form_invalid_long_otp(self):
        form = OTPVerificationForm(data={'otp': '12345'})
        self.assertFalse(form.is_valid())
        self.assertIn('Ensure this value has at most 4 characters (it has 5).', form.errors['otp'])


@override_settings(
    OOREDOO_SMS_URL='http://mock-ooredoo-sms.com',
    OOREDOO_CUSTOMER_ID='test_id',
    OOREDOO_USERNAME='test_user',
    OOREDOO_PASSWORD='test_password',
    OOREDOO_ORIGINATOR='TestSender',
    AUTHENTICATION_BACKENDS=('django.contrib.auth.backends.ModelBackend',)
)
class AccountViewsTest(TestCase):

    def setUp(self):
        self.client = Client()
        self.warehouse = Warehouse.objects.create(name="Test Warehouse")
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='password123',
            phone='1234567890',
            warehouse=self.warehouse
        )
        self.login_phone_url = reverse('login_phone')
        self.verify_otp_url = reverse('verify_otp')
        self.dashboard_url = '/dashboard/' # Assuming a dashboard URL exists

    def test_login_with_phone_get(self):
        response = self.client.get(self.login_phone_url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'registration/login_phone.html')

    @patch('accounts.utils.send_ooredoo_sms')
    @patch('random.randint', return_value=1234)
    def test_login_with_phone_post_success(self, mock_randint, mock_send_sms):
        mock_send_sms.return_value = True
        response = self.client.post(self.login_phone_url, {'phone': '1234567890'})
        self.assertRedirects(response, self.verify_otp_url)
        mock_send_sms.assert_called_once_with('1234567890', 1234)
        self.assertEqual(cache.get('otp_1234567890'), 1234)
        self.assertEqual(self.client.session.get('login_phone'), '1234567890')
        messages = list(response.context['messages'])
        self.assertEqual(len(messages), 1)
        self.assertEqual(str(messages[0]), 'OTP sent to your mobile number.')

    @patch('accounts.utils.send_ooredoo_sms')
    def test_login_with_phone_post_sms_fail(self, mock_send_sms):
        mock_send_sms.return_value = False
        response = self.client.post(self.login_phone_url, {'phone': '1234567890'})
        self.assertEqual(response.status_code, 200) # Stays on the same page
        self.assertTemplateUsed(response, 'registration/login_phone.html')
        messages = list(response.context['messages'])
        self.assertEqual(len(messages), 1)
        self.assertEqual(str(messages[0]), 'Failed to send SMS. Please try again.')

    def test_login_with_phone_post_invalid_form(self):
        response = self.client.post(self.login_phone_url, {'phone': '9999999999'}) # Unregistered phone
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'registration/login_phone.html')
        self.assertIn('This phone number is not registered.', response.context['form'].errors['phone'])

    def test_verify_otp_get_no_phone_in_session(self):
        response = self.client.get(self.verify_otp_url)
        self.assertRedirects(response, self.login_phone_url)

    def test_verify_otp_get_with_phone_in_session(self):
        session = self.client.session
        session['login_phone'] = '1234567890'
        session.save()
        response = self.client.get(self.verify_otp_url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'registration/verify_otp.html')
        self.assertEqual(response.context['phone'], '1234567890')

    def test_verify_otp_post_success(self):
        session = self.client.session
        session['login_phone'] = '1234567890'
        session.save()
        cache.set('otp_1234567890', 1234, timeout=300)

        response = self.client.post(self.verify_otp_url, {'otp': '1234'})
        self.assertRedirects(response, self.dashboard_url)
        self.assertIsNone(cache.get('otp_1234567890')) # OTP should be deleted
        self.assertNotIn('login_phone', self.client.session) # Session key should be deleted
        self.assertTrue(self.user.is_authenticated) # User should be logged in
        messages = list(response.context['messages'])
        self.assertEqual(len(messages), 1)
        self.assertEqual(str(messages[0]), 'Login Successful!')

    def test_verify_otp_post_invalid_otp(self):
        session = self.client.session
        session['login_phone'] = '1234567890'
        session.save()
        cache.set('otp_1234567890', 5678, timeout=300)

        response = self.client.post(self.verify_otp_url, {'otp': '1234'})
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'registration/verify_otp.html')
        messages = list(response.context['messages'])
        self.assertEqual(len(messages), 1)
        self.assertEqual(str(messages[0]), 'Invalid or Expired OTP.')

    def test_verify_otp_post_expired_otp(self):
        session = self.client.session
        session['login_phone'] = '1234567890'
        session.save()
        # Don't set OTP in cache, simulating expired OTP

        response = self.client.post(self.verify_otp_url, {'otp': '1234'})
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'registration/verify_otp.html')
        messages = list(response.context['messages'])
        self.assertEqual(len(messages), 1)
        self.assertEqual(str(messages[0]), 'Invalid or Expired OTP.')

    def test_verify_otp_post_unregistered_user_phone(self):
        session = self.client.session
        session['login_phone'] = '9999999999' # Unregistered phone
        session.save()
        cache.set('otp_9999999999', 1234, timeout=300)

        response = self.client.post(self.verify_otp_url, {'otp': '1234'})
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'registration/verify_otp.html')
        messages = list(response.context['messages'])
        self.assertEqual(len(messages), 1)
        self.assertEqual(str(messages[0]), 'User not found associated with this number.')


@override_settings(
    OOREDOO_SMS_URL='http://mock-ooredoo-sms.com',
    OOREDOO_CUSTOMER_ID='test_id',
    OOREDOO_USERNAME='test_user',
    OOREDOO_PASSWORD='test_password',
    OOREDOO_ORIGINATOR='TestSender',
)
class AccountUtilsTest(TestCase):

    @patch('requests.get')
    def test_send_ooredoo_sms_success(self, mock_requests_get):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = '<TransactionID>12345</TransactionID>'
        mock_requests_get.return_value = mock_response

        result = send_ooredoo_sms('1234567890', 1234)
        self.assertTrue(result)
        mock_requests_get.assert_called_once()
        args, kwargs = mock_requests_get.call_args
        self.assertIn('recipientPhone', kwargs['params'])
        self.assertEqual(kwargs['params']['recipientPhone'], '9741234567890') # Should add 974 prefix

    @patch('requests.get')
    def test_send_ooredoo_sms_fail_api_response(self, mock_requests_get):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = '<Error>Failed</Error>'
        mock_requests_get.return_value = mock_response

        result = send_ooredoo_sms('1234567890', 1234)
        self.assertFalse(result)
        mock_requests_get.assert_called_once()

    @patch('requests.get')
    def test_send_ooredoo_sms_fail_http_error(self, mock_requests_get):
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = 'Internal Server Error'
        mock_requests_get.return_value = mock_response

        result = send_ooredoo_sms('1234567890', 1234)
        self.assertFalse(result)
        mock_requests_get.assert_called_once()

    @patch('requests.get', side_effect=Exception('Connection Error'))
    def test_send_ooredoo_sms_exception(self, mock_requests_get):
        result = send_ooredoo_sms('1234567890', 1234)
        self.assertFalse(result)
        mock_requests_get.assert_called_once()

    def test_send_ooredoo_sms_phone_prefix(self):
        # Test with phone number already having '974'
        with patch('requests.get') as mock_requests_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.text = '<TransactionID>12345</TransactionID>'
            mock_requests_get.return_value = mock_response

            send_ooredoo_sms('9741234567890', 1234)
            args, kwargs = mock_requests_get.call_args
            self.assertEqual(kwargs['params']['recipientPhone'], '9741234567890')

        # Test with phone number without '974'
        with patch('requests.get') as mock_requests_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.text = '<TransactionID>12345</TransactionID>'
            mock_requests_get.return_value = mock_response

            send_ooredoo_sms('1234567890', 1234)
            args, kwargs = mock_requests_get.call_args
            self.assertEqual(kwargs['params']['recipientPhone'], '9741234567890')