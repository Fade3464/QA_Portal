from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .api_views import (
    AdministrationSummaryView,
    AuthenticationEventViewSet,
    BranchViewSet,
    CompanyViewSet,
    DialerViewSet,
    UserViewSet,
)

router = DefaultRouter()
router.register("companies", CompanyViewSet, basename="administration-company")
router.register("branches", BranchViewSet, basename="administration-branch")
router.register("dialers", DialerViewSet, basename="administration-dialer")
router.register("users", UserViewSet, basename="administration-user")
router.register("security-events", AuthenticationEventViewSet, basename="administration-security-event")

urlpatterns = [
    path("summary/", AdministrationSummaryView.as_view(), name="administration-summary"),
    path("", include(router.urls)),
]
