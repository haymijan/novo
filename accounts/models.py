# accounts/models.py

from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models
from decimal import Decimal
from stock.models import Warehouse

class CustomUserManager(BaseUserManager):

    def create_user(self, username, email, password=None, **extra_fields):

        if not email:
            raise ValueError('The Email field must be set')
        email = self.normalize_email(email)
        user = self.model(username=username, email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, username, email, password=None, **extra_fields):

        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('is_active', True)

        if extra_fields.get('is_staff') is not True:
            raise ValueError('Superuser must have is_staff=True.')
        if extra_fields.get('is_superuser') is not True:
            raise ValueError('Superuser must have is_superuser=True.')

        return self.create_user(username, email, password, **extra_fields)

class User(AbstractUser):
    warehouse = models.ForeignKey(
        Warehouse,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='users'
    )
    phone = models.CharField(max_length=20, blank=True, null=True)

    max_discount_percentage = models.DecimalField(
        max_digits=5, 
        decimal_places=2, 
        default=Decimal('0.00'),
        help_text="Maximum percentage discount this user can provide."
    )

    objects = CustomUserManager()

    def __str__(self):
        return self.username