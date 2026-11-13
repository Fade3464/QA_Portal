from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.accounts.models import User

from .models import Dialer, DialerCampaign
from .services import (
    sync_campaign_dialer_manager_access,
    sync_dialer_manager_project_access,
)


@receiver(post_save, sender=User, dispatch_uid="sync_dialer_manager_company_projects")
def sync_dialer_manager_projects_on_user_save(sender, instance, **kwargs):
    if not instance.is_superuser and instance.role == User.Role.DIALER_MANAGER:
        sync_dialer_manager_project_access(instance)


@receiver(post_save, sender=DialerCampaign, dispatch_uid="sync_new_campaign_dialer_managers")
def sync_dialer_managers_on_campaign_save(sender, instance, **kwargs):
    sync_campaign_dialer_manager_access(instance)


@receiver(post_save, sender=Dialer, dispatch_uid="resync_campaigns_after_dialer_move")
def sync_dialer_managers_on_dialer_save(sender, instance, **kwargs):
    # Normally campaign ownership does not change. This also keeps access sane
    # if an administrator moves an existing dialer to another company/branch.
    for campaign in instance.campaigns.select_related("dialer__branch").all():
        sync_campaign_dialer_manager_access(campaign)
