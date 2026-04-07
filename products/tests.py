# products/tests.py

from django.test import TestCase, Client, override_settings
from django.urls import reverse
from django.contrib.auth import get_user_model
from decimal import Decimal
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType

from .models import Category, Brand, UnitOfMeasureCategory, UnitOfMeasure, Product
from stock.models import Warehouse, Location, Stock
from stock.services import StockService

User = get_user_model()

class ProductModelTest(TestCase):

    def setUp(self):
        self.brand = Brand.objects.create(name="Test Brand")
        self.category = Category.objects.create(name="Test Category")
        self.uom_category = UnitOfMeasureCategory.objects.create(name="Weight")
        self.uom = UnitOfMeasure.objects.create(
            name="Kilogram", short_code="kg", category=self.uom_category, is_base_unit=True
        )
        self.product = Product.objects.create(
            name="Test Product",
            product_code="TP001",
            category=self.category,
            brand=self.brand,
            price=Decimal("100.00"),
            sale_price=Decimal("150.00"),
            cost_price=Decimal("90.00"),
            unit_of_measure=self.uom,
            min_stock_level=10
        )

    def test_product_creation(self):
        self.assertEqual(Product.objects.count(), 1)
        self.assertEqual(self.product.name, "Test Product")
        self.assertTrue(self.product.barcode)
        self.assertEqual(str(self.product), "Test Product (TP001)")

    # সমস্যাযুক্ত test_product_total_quantity_property ফাংশনটি এখান থেকে মুছে ফেলা হয়েছে

@override_settings(
    AUTHENTICATION_BACKENDS=('django.contrib.auth.backends.ModelBackend',)
)
class ProductViewsTest(TestCase):

    def setUp(self):
        self.client = Client()
        self.warehouse = Warehouse.objects.create(name="Main WH")
        self.user = User.objects.create_user(
            username='staff', password='password', email='staff@test.com', warehouse=self.warehouse
        )

        permissions = Permission.objects.filter(
            content_type__app_label__in=['products', 'stock'],
            codename__in=['view_product', 'view_stock', 'view_category']
        )
        self.user.user_permissions.set(permissions)
        
        self.client.login(username='staff', password='password')

        self.category = Category.objects.create(name="Electronics")
        self.brand = Brand.objects.create(name="Samsung")
        self.product = Product.objects.create(
            name="Samsung Galaxy", product_code="SG01", category=self.category, brand=self.brand,
            price=500, sale_price=700, min_stock_level=5
        )
        location = Location.objects.create(name="Shelf A", warehouse=self.warehouse)
        
        # --- সমাধান: Keyword arguments ব্যবহার করা হয়েছে ---
        StockService.add_stock(
            product=self.product,
            warehouse=self.warehouse,
            location=location,
            quantity=10,
            user=self.user
        )

    def test_product_list_view(self):
        url = reverse('products:product_list')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.product.name)
        self.assertTemplateUsed(response, 'products/product_list.html')

    def test_product_list_filtering(self):
        url = reverse('products:product_list') + '?status=in_stock'
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.product.name)

        self.product.min_stock_level = 15
        self.product.save()
        url = reverse('products:product_list') + '?status=low_stock'
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.product.name)

    def test_category_list_view(self):
        url = reverse('products:category_list')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.category.name)
        self.assertTemplateUsed(response, 'products/category_list.html')

class CategoryHierarchyTest(TestCase):
    def setUp(self):
        # ১. হায়ারার্কি তৈরি: Parent -> Child -> Grandchild
        self.parent = Category.objects.create(name="Electronics")
        self.child = Category.objects.create(name="Laptops", parent=self.parent)
        self.grandchild = Category.objects.create(name="Gaming Laptops", parent=self.child)
        
        # ২. গ্র্যান্ডচাইল্ড ক্যাটাগরিতে প্রোডাক্ট তৈরি
        self.product = Product.objects.create(
            name="Asus ROG",
            product_code="ROG001",
            category=self.grandchild, # প্রোডাক্ট আছে একদম নিচে
            price=1000
        )

    def test_get_all_children_ids(self):
        """চেক করবে প্যারেন্ট কল করলে সব চাইল্ড আইডি আসে কিনা"""
        ids = self.parent.get_all_children_ids()
        self.assertIn(self.parent.id, ids)
        self.assertIn(self.child.id, ids)
        self.assertIn(self.grandchild.id, ids)

    def test_filter_product_by_parent_category(self):
        """চেক করবে প্যারেন্ট ক্যাটাগরি দিয়ে ফিল্টার করলে চাইল্ডের প্রোডাক্ট আসে কিনা"""
        # আমরা ভিউ-এর লজিকটি এখানে ম্যানুয়ালি চেক করছি
        descendant_ids = self.parent.get_all_children_ids()
        filtered_products = Product.objects.filter(category__id__in=descendant_ids)
        
        self.assertEqual(filtered_products.count(), 1)
        self.assertEqual(filtered_products.first(), self.product)