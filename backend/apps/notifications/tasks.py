from __future__ import annotations

import html
import logging

from celery import shared_task
from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.utils import timezone

from apps.calls.models import Review, ReviewWorkflowEvent

logger = logging.getLogger(__name__)


def _report_body(review) -> tuple[str, str]:
    agent = review.call.agent_name or review.call.agent_user or "Unknown agent"
    critical = ", ".join(review.critical_errors) or "None"
    score_display = (
        "Not required — automatic fail"
        if review.critical_errors and review.score is None
        else f"{review.score}%"
    )
    lines = [
        "QA report submitted",
        "",
        f"Agent: {agent}",
        f"Team: {review.call.team.name if review.call.team_id else 'Unassigned'}",
        f"QA analyst: {review.reviewer.full_name}",
        f"Score: {score_display}",
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
            ("Score", score_display),
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


def _returned_report_body(event) -> tuple[str, str]:
    review = event.review
    agent = review.call.agent_name or review.call.agent_user or "Unknown agent"
    leader = event.actor.full_name
    reason = event.note
    revision_number = ReviewWorkflowEvent.objects.filter(
        review=review,
        to_status=Review.LeaderStatus.RETURNED_TO_QA,
        created_at__lte=event.created_at,
    ).count()
    reassessment_url = (
        f"{settings.FRONTEND_URL.rstrip('/')}/calls?analysis={review.call_id}"
    )
    text = "\n".join(
        [
            "QA report returned for reassessment",
            "",
            f"Agent: {agent}",
            f"Team: {review.call.team.name if review.call.team_id else 'Unassigned'}",
            f"Returned by: {leader}",
            f"Revision: {revision_number}",
            "",
            "Reason supplied by the Team Leader:",
            reason,
            "",
            "Review the feedback, update the evaluation, and resubmit it when ready.",
            f"Open the report: {reassessment_url}",
        ]
    )
    html_body = (
        "<h2>QA report returned for reassessment</h2>"
        f"<p><strong>Agent:</strong> {html.escape(agent)}<br>"
        f"<strong>Team:</strong> {html.escape(review.call.team.name if review.call.team_id else 'Unassigned')}<br>"
        f"<strong>Returned by:</strong> {html.escape(leader)}<br>"
        f"<strong>Revision:</strong> {revision_number}</p>"
        "<h3>Reason supplied by the Team Leader</h3>"
        f"<p>{html.escape(reason)}</p>"
        "<p>Review the feedback, update the evaluation, and resubmit it when ready.</p>"
        f"<p><a href='{html.escape(reassessment_url)}'>Open report for reassessment</a></p>"
    )
    return text, html_body


@shared_task(
    name="notifications.send_review_returned_email",
    bind=True,
    max_retries=4,
    acks_late=True,
    reject_on_worker_lost=True,
    soft_time_limit=45,
    time_limit=60,
)
def send_review_returned_email(self, workflow_event_id: str):
    try:
        event = ReviewWorkflowEvent.objects.select_related(
            "review__call__team", "review__reviewer", "actor"
        ).get(pk=workflow_event_id)
    except ReviewWorkflowEvent.DoesNotExist:
        logger.warning(
            "Review return event disappeared before email delivery",
            extra={"workflow_event_id": workflow_event_id},
        )
        return {"status": "missing"}
    if event.to_status != Review.LeaderStatus.RETURNED_TO_QA:
        return {"status": "not_return_event"}
    if event.email_status == Review.EmailStatus.SENT:
        return {"status": "already_sent"}
    if not settings.QA_RETURN_EMAIL_ENABLED:
        ReviewWorkflowEvent.objects.filter(pk=event.pk).update(
            email_status=Review.EmailStatus.DISABLED
        )
        return {"status": "disabled"}
    recipient = event.review.reviewer.email
    if not recipient:
        ReviewWorkflowEvent.objects.filter(pk=event.pk).update(
            email_status=Review.EmailStatus.FAILED,
            email_last_error="The QA analyst does not have an email address.",
        )
        return {"status": "missing_recipient"}
    text, html_body = _returned_report_body(event)
    try:
        message = EmailMultiAlternatives(
            subject=(
                "QA report returned: "
                f"{event.review.call.agent_name or event.review.call.agent_user}"
            ),
            body=text,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[recipient],
        )
        message.attach_alternative(html_body, "text/html")
        message.send(fail_silently=False)
    except Exception as exc:
        ReviewWorkflowEvent.objects.filter(pk=event.pk).update(
            email_status=Review.EmailStatus.FAILED,
            email_last_error=str(exc)[:1000],
        )
        logger.exception(
            "QA report return email delivery failed",
            extra={
                "workflow_event_id": workflow_event_id,
                "review_id": str(event.review_id),
            },
        )
        raise self.retry(exc=exc, countdown=min(600, 30 * 2**self.request.retries))
    ReviewWorkflowEvent.objects.filter(pk=event.pk).update(
        email_status=Review.EmailStatus.SENT,
        email_sent_at=timezone.now(),
        email_last_error="",
    )
    logger.info(
        "QA report return email delivered",
        extra={
            "workflow_event_id": workflow_event_id,
            "review_id": str(event.review_id),
        },
    )
    return {"status": "sent"}
