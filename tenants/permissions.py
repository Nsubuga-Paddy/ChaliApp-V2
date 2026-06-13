from rest_framework.permissions import BasePermission, SAFE_METHODS

from .models import Company, CompanyMembership


def resolve_request_company(request):
    company = getattr(request, 'company', None)
    if company is not None:
        return company

    company_id = request.headers.get('X-Company-ID')
    if not company_id:
        return None
    try:
        company = Company.objects.get(pk=int(company_id), is_active=True)
    except (Company.DoesNotExist, ValueError, TypeError):
        return None

    request.company = company
    if request.user and request.user.is_authenticated and request.user.user_type == 'staff':
        request.company_membership = CompanyMembership.objects.filter(
            user=request.user,
            company=company,
            is_active=True,
        ).first()
    return company


class IsPlatformAdmin(BasePermission):
    def has_permission(self, request, view):
        return (
            request.user
            and request.user.is_authenticated
            and request.user.user_type == 'platform_admin'
        )


class IsStaffUser(BasePermission):
    def has_permission(self, request, view):
        return (
            request.user
            and request.user.is_authenticated
            and request.user.user_type in ('staff', 'platform_admin')
        )


class IsCustomer(BasePermission):
    def has_permission(self, request, view):
        return (
            request.user
            and request.user.is_authenticated
            and request.user.user_type == 'customer'
        )


class HasCompanyAccess(BasePermission):
    message = 'Valid X-Company-ID header required for this company.'

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        company = resolve_request_company(request)
        if request.user.user_type == 'platform_admin':
            return company is not None
        if request.user.user_type != 'staff':
            return False
        if company is None:
            return False
        return CompanyMembership.objects.filter(
            user=request.user,
            company=company,
            is_active=True,
        ).exists()


class IsCompanyAdmin(BasePermission):
    def has_permission(self, request, view):
        membership = getattr(request, 'company_membership', None)
        if request.user.user_type == 'platform_admin':
            return getattr(request, 'company', None) is not None
        return membership is not None and membership.role == 'admin'


class IsCompanyAgentOrAdmin(BasePermission):
    def has_permission(self, request, view):
        membership = getattr(request, 'company_membership', None)
        if request.user.user_type == 'platform_admin':
            return getattr(request, 'company', None) is not None
        return membership is not None and membership.role in ('admin', 'agent')


class ReadOnly(BasePermission):
    def has_permission(self, request, view):
        return request.method in SAFE_METHODS
