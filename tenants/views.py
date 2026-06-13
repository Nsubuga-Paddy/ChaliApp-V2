from rest_framework import generics, permissions, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from .ingestion import index_legacy_document, index_source_document
from .models import (
    Company,
    CompanyAIConfig,
    CompanyMembership,
    KnowledgeDocument,
    KnowledgeSourceDocument,
    KnowledgeWebSource,
)
from .permissions import HasCompanyAccess, IsCompanyAdmin, IsCompanyAgentOrAdmin, IsPlatformAdmin, IsStaffUser
from .serializers import (
    CompanyAIConfigSerializer,
    CompanyCreateUpdateSerializer,
    CompanyDetailSerializer,
    CompanyListSerializer,
    CompanyMembershipSerializer,
    CompanyStaffSerializer,
    KnowledgeChunkSerializer,
    KnowledgeDocumentSerializer,
    KnowledgeSourceDocumentSerializer,
    KnowledgeWebSourceSerializer,
    StaffCompanyMembershipSerializer,
)
from .web_ingestion import index_web_source


class PublicCompanyListView(generics.ListAPIView):
    queryset = Company.objects.filter(is_active=True)
    serializer_class = CompanyListSerializer
    permission_classes = [permissions.AllowAny]


class PublicCompanyDetailView(generics.RetrieveAPIView):
    queryset = Company.objects.filter(is_active=True)
    serializer_class = CompanyDetailSerializer
    lookup_field = 'slug'
    permission_classes = [permissions.AllowAny]


class StaffMyCompaniesView(generics.ListAPIView):
    serializer_class = StaffCompanyMembershipSerializer
    permission_classes = [permissions.IsAuthenticated, IsStaffUser]

    def get_queryset(self):
        return CompanyMembership.objects.filter(
            user=self.request.user,
            is_active=True,
            company__is_active=True,
        ).select_related('company')


class PlatformCompanyViewSet(viewsets.ModelViewSet):
    queryset = Company.objects.all()
    permission_classes = [permissions.IsAuthenticated, IsPlatformAdmin]

    def get_serializer_class(self):
        if self.action in ('create', 'update', 'partial_update'):
            return CompanyCreateUpdateSerializer
        return CompanyStaffSerializer

    def perform_create(self, serializer):
        company = serializer.save()
        CompanyAIConfig.objects.get_or_create(company=company)


class StaffCompanyDetailView(generics.RetrieveUpdateAPIView):
    serializer_class = CompanyStaffSerializer
    permission_classes = [permissions.IsAuthenticated, HasCompanyAccess, IsCompanyAdmin]

    def get_object(self):
        return self.request.company


class CompanyAIConfigView(generics.RetrieveUpdateAPIView):
    serializer_class = CompanyAIConfigSerializer
    permission_classes = [permissions.IsAuthenticated, HasCompanyAccess, IsCompanyAdmin]

    def get_object(self):
        config, _ = CompanyAIConfig.objects.get_or_create(company=self.request.company)
        return config


class CompanyMembershipViewSet(viewsets.ModelViewSet):
    serializer_class = CompanyMembershipSerializer
    permission_classes = [permissions.IsAuthenticated, HasCompanyAccess, IsCompanyAdmin]

    def get_queryset(self):
        return CompanyMembership.objects.filter(
            company=self.request.company,
        ).select_related('user', 'company')

    def perform_create(self, serializer):
        serializer.save(company=self.request.company)


class KnowledgeDocumentViewSet(viewsets.ModelViewSet):
    serializer_class = KnowledgeDocumentSerializer
    permission_classes = [permissions.IsAuthenticated, HasCompanyAccess, IsCompanyAgentOrAdmin]
    filterset_fields = ('category', 'is_published')
    search_fields = ('title', 'content', 'tags')

    def get_queryset(self):
        return KnowledgeDocument.objects.filter(company=self.request.company)

    def perform_create(self, serializer):
        document = serializer.save(company=self.request.company, created_by=self.request.user)
        index_legacy_document(document)

    def perform_update(self, serializer):
        document = serializer.save()
        index_legacy_document(document)

    def perform_destroy(self, instance):
        instance.chunks.all().delete()
        instance.delete()

    @action(detail=True, methods=['post'])
    def reindex(self, request, pk=None):
        document = self.get_object()
        index_legacy_document(document)
        return Response(self.get_serializer(document).data)


class KnowledgeSourceDocumentViewSet(viewsets.ModelViewSet):
    serializer_class = KnowledgeSourceDocumentSerializer
    permission_classes = [permissions.IsAuthenticated, HasCompanyAccess, IsCompanyAgentOrAdmin]
    filterset_fields = ('status', 'file_type', 'is_published')
    search_fields = ('title', 'error_message')

    def get_queryset(self):
        return KnowledgeSourceDocument.objects.filter(
            company=self.request.company,
        ).select_related('company', 'uploaded_by')

    def perform_create(self, serializer):
        source = serializer.save(
            company=self.request.company,
            uploaded_by=self.request.user,
        )
        index_source_document(source)

    def perform_update(self, serializer):
        source = serializer.save()
        index_source_document(source)

    @action(detail=True, methods=['post'])
    def reindex(self, request, pk=None):
        source = self.get_object()
        index_source_document(source)
        return Response(self.get_serializer(source).data)

    @action(detail=True, methods=['get'])
    def chunks(self, request, pk=None):
        source = self.get_object()
        serializer = KnowledgeChunkSerializer(
            source.chunks.filter(is_active=True).order_by('chunk_index'),
            many=True,
            context={'request': request},
        )
        return Response(serializer.data)


class KnowledgeWebSourceViewSet(viewsets.ModelViewSet):
    serializer_class = KnowledgeWebSourceSerializer
    permission_classes = [permissions.IsAuthenticated, HasCompanyAccess, IsCompanyAgentOrAdmin]
    filterset_fields = ('status', 'crawl_mode', 'refresh_interval', 'is_published')
    search_fields = ('title', 'url', 'last_error')

    def get_queryset(self):
        return KnowledgeWebSource.objects.filter(
            company=self.request.company,
        ).select_related('company', 'created_by')

    def perform_create(self, serializer):
        source = serializer.save(
            company=self.request.company,
            created_by=self.request.user,
        )
        source.schedule_next_crawl()
        source.save(update_fields=['next_crawl_at', 'updated_at'])
        index_web_source(source)

    def perform_update(self, serializer):
        source = serializer.save()
        source.schedule_next_crawl()
        source.save(update_fields=['next_crawl_at', 'updated_at'])
        index_web_source(source)

    @action(detail=True, methods=['post'])
    def reindex(self, request, pk=None):
        source = self.get_object()
        index_web_source(source)
        return Response(self.get_serializer(source).data)

    @action(detail=True, methods=['get'])
    def chunks(self, request, pk=None):
        source = self.get_object()
        serializer = KnowledgeChunkSerializer(
            source.chunks.filter(is_active=True).order_by('chunk_index'),
            many=True,
            context={'request': request},
        )
        return Response(serializer.data)
