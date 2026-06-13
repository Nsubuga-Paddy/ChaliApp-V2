from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView

from .views import EmailTokenObtainPairView, HealthView, MeView, RegisterView, StaffRegisterView

urlpatterns = [
    path('health/', HealthView.as_view(), name='health'),
    path('register/', RegisterView.as_view(), name='register'),
    path('staff/register/', StaffRegisterView.as_view(), name='staff-register'),
    path('login/', EmailTokenObtainPairView.as_view(), name='login'),
    path('token/refresh/', TokenRefreshView.as_view(), name='token-refresh'),
    path('me/', MeView.as_view(), name='me'),
]
