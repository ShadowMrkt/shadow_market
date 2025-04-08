from typing import List
from .models import Product

def get_enhanced_recommendations_for_user(user) -> List[Product]:
    return list(Product.objects.filter(available=True)[:5])
