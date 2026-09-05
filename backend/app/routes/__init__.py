from .auth import bp as auth_bp
from .classify import bp as classify_bp
from .meals import bp as meals_bp
from .products import bp as products_bp

__all__ = ["auth_bp", "classify_bp", "meals_bp", "products_bp"]
