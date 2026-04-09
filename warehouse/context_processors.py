from django.conf import settings


def company_context(request):
    return {
        "company_name": getattr(settings, "COMPANY_NAME", "Татнефтеснаб"),
        "company_full_name": getattr(settings, "COMPANY_FULL_NAME", ""),
    }
