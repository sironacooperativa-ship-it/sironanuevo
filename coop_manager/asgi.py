"""
ASGI config for coop_manager project.
"""

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "coop_manager.settings")

application = get_asgi_application()

