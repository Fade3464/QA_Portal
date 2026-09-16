from __future__ import annotations

import html
import logging

from celery import shared_task
from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.utils import timezone

from apps.calls.models import Review

logger = logging.getLogger(__name__)


def _report_body(review) -> tuple[str, str]:
    agent = review.call.agent_name or review.call.agent_user or "Unknown agent"
    critical = ", ".join(review.critical_errors) or "None"
    lines = [
        "QA report submitted",
        "",
        f"Agent: {agent}",
        f"Team: {review.call.team.name if review.call.team_id else 'Unassigned'}",
        f"QA analyst: {review.reviewer.full_name}",
        f"Score: {review.score}%",
        f"Rating: {review.get_rating_display()}",
        f"Status: {review.get_outcome_display()}",
        f"Critical errors: {critical}",
        "",
        f"Feedback: {review.feedback_summary or 'Not specified'}",
        f"Strengths: {review.strengths or 'Not specified'}",
        f"Expected behavior: {review.expected_behavior or 'Not specified'}",
        f"Coaching plan: {review.coaching_plan or 'To be determined by Team Leader'}",
        "",
        f"Open reports: {settings.FRONTEND_URL.rstrip('/')}/queue",
    ]
    text = "\n".join(lines)
    rows = "".join(
        f"<tr><td>{html.escape(label)}</td><td>{html.escape(value)}</td></tr>"
        for label, value in (
            ("Agent", agent),
            ("Team", review.call.team.name if review.call.team_id else "Unassigned"),
            ("QA analyst", review.reviewer.full_name),
            ("Score", f"{review.score}%"),
            ("Rating", review.get_rating_display()),
            ("Status", review.get_outcome_display()),
            ("Critical errors", critical),
        )
    )
    html_body = (
        "<h2>QA report submitted</h2><table cellpadding='8'>"
        f"{rows}</table><h3>Feedback</h3><p>{html.escape(review.feedback_summary or 'Not specified')}</p>"
        f"<h3>Strengths</h3><p>{html.escape(review.strengths or 'Not specified')}</p>"
        f"<h3>Expected behavior</h3><p>{html.escape(review.expected_behavior or 'Not specified')}</p>"
        f"<h3>Coaching plan</h3><p>{html.escape(review.coaching_plan or 'To be determined by Team Leader')}</p>"
        f"<p><a href='{html.escape(settings.FRONTEND_URL.rstrip('/'))}/queue'>Open QA reports</a></p>"
    )
    return text, html_body


@shared_task(
    name="notifications.send_review_report_email",
    bind=True,
    max_retries=4,
    acks_late=True,
    reject_on_worker_lost=True,
    soft_time_limit=45,
    time_limit=60,
)
def send_review_report_email(self, review_id: str):
    try:
        review = Review.objects.select_related(
            "call__team", "reviewer", "team_leader"
        ).get(pk=review_id)
    except Review.DoesNotExist:
        logger.warning(
            "QA report disappeared before email delivery",
            extra={"review_id": review_id},
        )
        return {"status": "missing"}
    if review.email_status == Review.EmailStatus.SENT:
        return {"status": "already_sent"}
    if not settings.QA_REPORT_EMAIL_ENABLED:
        Review.objects.filter(pk=review.pk).update(
            email_status=Review.EmailStatus.DISABLED
        )
        return {"status": "disabled"}
    if review.status != Review.Status.COMPLETED or not review.team_leader_id:
        return {"status": "not_ready"}
    text, html_body = _report_body(review)
    try:
        message = EmailMultiAlternatives(
            subject=f"QA report: {review.call.agent_name or review.call.agent_user} — {review.score}%",
            body=text,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[review.team_leader.email],
        )
        message.attach_alternative(html_body, "text/html")
        message.send(fail_silently=False)
    except Exception as exc:
        Review.objects.filter(pk=review.pk).update(
            email_status=Review.EmailStatus.FAILED,
            email_last_error=str(exc)[:1000],
        )
        logger.exception(
            "QA report email delivery failed", extra={"review_id": review_id}
        )
        raise self.retry(exc=exc, countdown=min(600, 30 * 2**self.request.retries))
    Review.objects.filter(pk=review.pk).update(
        email_status=Review.EmailStatus.SENT,
        email_sent_at=timezone.now(),
        email_last_error="",
    )
    logger.info("QA report email delivered", extra={"review_id": review_id})
    return {"status": "sent"}
