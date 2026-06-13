from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model

from tenants.models import Company, CompanyAIConfig, CompanyMembership, KnowledgeDocument

User = get_user_model()


class Command(BaseCommand):
    help = 'Create demo platform admin, company, staff, customer, and sample knowledge base.'

    def handle(self, *args, **options):
        admin, created = User.objects.get_or_create(
            email='admin@chali.app',
            defaults={
                'username': 'platform_admin',
                'user_type': User.UserType.PLATFORM_ADMIN,
                'is_staff': True,
                'is_superuser': True,
            },
        )
        if created:
            admin.set_password('admin12345')
            admin.save()
            self.stdout.write(self.style.SUCCESS('Created platform admin: admin@chali.app / admin12345'))
        else:
            self.stdout.write('Platform admin already exists.')

        company, created = Company.objects.get_or_create(
            slug='demo-company',
            defaults={
                'name': 'Demo Company',
                'description': 'Sample company for ChaliAssistant testing.',
                'contact_email': 'support@democompany.com',
                'enable_voice': True,
                'enable_orders': True,
                'enable_bookings': True,
            },
        )
        CompanyAIConfig.objects.get_or_create(company=company)
        if created:
            self.stdout.write(self.style.SUCCESS(f'Created company: {company.name}'))

        staff, created = User.objects.get_or_create(
            email='staff@democompany.com',
            defaults={
                'username': 'demo_staff',
                'user_type': User.UserType.STAFF,
                'first_name': 'Demo',
                'last_name': 'Agent',
            },
        )
        if created:
            staff.set_password('staff12345')
            staff.save()
        CompanyMembership.objects.get_or_create(
            user=staff,
            company=company,
            defaults={'role': CompanyMembership.Role.ADMIN},
        )
        self.stdout.write(self.style.SUCCESS('Staff user: staff@democompany.com / staff12345'))

        customer, created = User.objects.get_or_create(
            email='customer@example.com',
            defaults={
                'username': 'demo_customer',
                'user_type': User.UserType.CUSTOMER,
                'first_name': 'Demo',
                'last_name': 'Customer',
            },
        )
        if created:
            customer.set_password('customer12345')
            customer.save()
        self.stdout.write(self.style.SUCCESS('Customer user: customer@example.com / customer12345'))

        if not KnowledgeDocument.objects.filter(company=company).exists():
            KnowledgeDocument.objects.create(
                company=company,
                title='Refund Policy',
                category='Policies',
                content=(
                    'Customers may request a refund within 14 days of purchase. '
                    'Refunds are processed within 5-7 business days. '
                    'Contact support with your order number to start a refund request.'
                ),
                tags='refund,policy,support',
                created_by=staff,
            )
            KnowledgeDocument.objects.create(
                company=company,
                title='Business Hours',
                category='General',
                content='We are open Monday to Friday, 8:00 AM to 6:00 PM EAT. Weekend support is AI-only.',
                tags='hours,availability',
                created_by=staff,
            )
            self.stdout.write(self.style.SUCCESS('Added sample knowledge base documents.'))

        self.stdout.write(self.style.SUCCESS('Bootstrap complete.'))
