from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    class UserType(models.TextChoices):
        CUSTOMER = 'customer', 'Customer'
        STAFF = 'staff', 'Company Staff'
        PLATFORM_ADMIN = 'platform_admin', 'Platform Admin'

    email = models.EmailField(unique=True)
    user_type = models.CharField(
        max_length=20,
        choices=UserType.choices,
        default=UserType.CUSTOMER,
    )
    phone = models.CharField(max_length=30, blank=True)

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['username']

    class Meta:
        ordering = ['-date_joined']

    def __str__(self):
        return self.email

    @property
    def is_customer(self):
        return self.user_type == self.UserType.CUSTOMER

    @property
    def is_staff_member(self):
        return self.user_type == self.UserType.STAFF

    @property
    def is_platform_admin(self):
        return self.user_type == self.UserType.PLATFORM_ADMIN
