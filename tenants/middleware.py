from .models import Company, CompanyMembership


class CompanyContextMiddleware:
    """Resolves X-Company-ID for staff/platform routes."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.company = None
        request.company_membership = None

        company_id = request.headers.get('X-Company-ID')
        if company_id and request.user.is_authenticated:
            try:
                company = Company.objects.get(pk=int(company_id), is_active=True)
                request.company = company
                if request.user.user_type == 'staff':
                    request.company_membership = CompanyMembership.objects.filter(
                        user=request.user,
                        company=company,
                        is_active=True,
                    ).first()
            except (Company.DoesNotExist, ValueError, TypeError):
                pass

        return self.get_response(request)
