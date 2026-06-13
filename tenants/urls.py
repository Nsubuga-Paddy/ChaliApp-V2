from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    CompanyAIConfigView,
    CompanyMembershipViewSet,
    KnowledgeDocumentViewSet,
    KnowledgeSourceDocumentViewSet,
    KnowledgeWebSourceViewSet,
    PlatformCompanyViewSet,
    PublicCompanyDetailView,
    PublicCompanyListView,
    StaffCompanyDetailView,
    StaffMyCompaniesView,
)

router = DefaultRouter()
router.register(r'platform/companies', PlatformCompanyViewSet, basename='platform-company')
router.register(r'staff/memberships', CompanyMembershipViewSet, basename='company-membership')
router.register(r'staff/knowledge', KnowledgeDocumentViewSet, basename='knowledge')
router.register(r'staff/knowledge-sources', KnowledgeSourceDocumentViewSet, basename='knowledge-source')
router.register(r'staff/knowledge-web-sources', KnowledgeWebSourceViewSet, basename='knowledge-web-source')

urlpatterns = [
    path('companies/', PublicCompanyListView.as_view(), name='company-list'),
    path('companies/<slug:slug>/', PublicCompanyDetailView.as_view(), name='company-detail'),
    path('staff/my-companies/', StaffMyCompaniesView.as_view(), name='staff-my-companies'),
    path('staff/company/', StaffCompanyDetailView.as_view(), name='staff-company-detail'),
    path('staff/ai-config/', CompanyAIConfigView.as_view(), name='staff-ai-config'),
    path('', include(router.urls)),
]
