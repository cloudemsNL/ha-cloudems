"""CloudEMS Providers — externe platform integraties."""
from .base import (
    CloudEMSProvider, OAuth2Mixin, ProviderDevice, ProviderStatus,
    register_provider, create_provider, get_all_providers,
    list_providers_by_category, ALL_UPDATE_HINTS,
)

# Laad alle provider modules zodat @register_provider decorators uitvoeren
from . import inverters      # noqa: F401
from . import ev_vehicles    # noqa: F401
from . import appliances     # noqa: F401
from . import energy_suppliers  # noqa: F401
from . import heating        # noqa: F401

__all__ = [
    "CloudEMSProvider", "OAuth2Mixin", "ProviderDevice", "ProviderStatus",
    "register_provider", "create_provider", "get_all_providers",
    "list_providers_by_category", "ALL_UPDATE_HINTS",
]
