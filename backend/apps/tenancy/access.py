from .models import DialerCampaign


def branch_projects(user):
    """Dynamic project access for a supervisor's company and branch."""
    if not user.company_id or not user.branch_id:
        return DialerCampaign.objects.none()
    return DialerCampaign.objects.filter(
        dialer__branch_id=user.branch_id,
        dialer__branch__company_id=user.company_id,
    ).select_related("dialer")
