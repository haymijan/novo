# inventory/templatetags/inventory_filters.py

from django import template
from decimal import Decimal

register = template.Library()

@register.filter
def mul(value, arg):
    """
    Multiplies the value with the argument.
    Usage: {{ value|mul:arg }}
    """
    try:
        return float(value) * float(arg)
    except (ValueError, TypeError):
        return ''

@register.filter
def sub(value, arg):
    """Subtracts the arg from the value."""
    try:
        return Decimal(value) - Decimal(arg)
    except (ValueError, TypeError):
        return ''