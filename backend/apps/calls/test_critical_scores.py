import json
from decimal import Decimal

from cryptography.fernet import Fernet
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.analytics.services.core import _summary
from apps.analytics.services.performance import get_qa_overview
from apps.notifications.models import SystemNotification
from apps.tenancy.models import QAProjectAssignment

from . import tests as fixtures
from .models import CallEvent, Review, ReviewWorkflowEvent
from .scorecard import scorecard_payload


@override_settings(DIALER_CREDENTIAL_KEY=Fernet.generate_key().decode(), AI_ENABLED=True)
class CriticalFinalScoreTests(TestCase):
    def setUp(self):
        fixtures.AnalysisReservationTests.setUp(self)
        self.client.force_login(self.qa_one)

    def url(self, name):
        return reverse(name, kwargs={"pk": self.call.pk})

    def test_draft_add_remove_critical_preserves_answers_and_restores_final_score(self):
        self.client.post(self.url("call-reserve"))
        scores = fixtures.AnalysisReservationTests.full_scores(self)
        response = self.client.patch(
            self.url("call-review-draft"),
            {"scores": scores, "critical_errors": ["misrepresentation"],
             "score": 99, "scorecard_score": 12},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["score"], "0.00")
        self.assertEqual(response.json()["scorecard_score"], "100.00")
        self.assertEqual(response.json()["scores"], scores)
        response = self.client.patch(self.url("call-review-draft"),
                                     {"critical_errors": []}, content_type="application/json")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["score"], "100.00")
        self.assertEqual(response.json()["scorecard_score"], "100.00")
        response = self.client.post(self.url("call-review-submit"),
                                    {"critical_errors": ["misrepresentation"], "score": 99},
                                    content_type="application/json")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["score"], "0.00")
        self.assertEqual(response.json()["scorecard_score"], "100.00")
        self.assertEqual(response.json()["earned_points"], "100.00")
        self.assertEqual(response.json()["applicable_points"], "100.00")

    def test_reassessment_removing_critical_restores_calculated_score(self):
        scores = fixtures.AnalysisReservationTests.full_scores(self)
        Review.objects.create(
            call=self.call, reviewer=self.qa_one, team_leader=self.team_leader,
            status=Review.Status.REVISION_REQUIRED, scores=scores, score=0,
            scorecard_score=100, critical_errors=["misrepresentation"],
            rating=Review.Rating.AUTOMATIC_FAIL, outcome=Review.Outcome.IMMEDIATE_ESCALATION,
            leader_status=Review.LeaderStatus.RETURNED_TO_QA,
        )
        response = self.client.post(self.url("call-review-submit"),
                                    {"critical_errors": []}, content_type="application/json")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["score"], "100.00")
        self.assertEqual(response.json()["scorecard_score"], "100.00")
        self.assertEqual(response.json()["rating"], Review.Rating.EXCELLENT)

    def test_submitted_critical_score_is_protected_at_model_and_database(self):
        review = Review.objects.create(call=self.call, reviewer=self.qa_one,
                                       status=Review.Status.COMPLETED, score=0,
                                       scorecard_score=100, critical_errors=["misrepresentation"])
        for status in (Review.Status.COMPLETED, Review.Status.DISPUTED):
            for score in (None, Decimal("99.00")):
                with self.subTest(status=status, score=score):
                    review.status = status
                    review.score = score
                    with self.assertRaises(ValidationError) as error:
                        review.clean()
                    self.assertIn("score", error.exception.message_dict)
                    with self.assertRaises(IntegrityError), transaction.atomic():
                        Review.objects.filter(pk=review.pk).update(status=status, score=score)
                    review.refresh_from_db()

    def test_dashboards_ai_and_filters_include_critical_zero_scores(self):
        scores = fixtures.AnalysisReservationTests.full_scores(self)
        for index, (scope, final, raw, errors) in enumerate((
            ("full", 80, 80, []),
            ("full", 0, 100, ["misrepresentation"]),
            ("partial", 0, None, ["privacy_violation"]),
            ("not_evaluable", None, None, []),
            ("zero_defect", None, None, []),
        )):
            call = CallEvent.objects.create(
                dialer=self.dialer, branch=self.branch, team=self.team, campaign="analysis",
                event_key=f"critical-score-{index}".ljust(64, "0"), event_type="dispo",
            )
            Review.objects.create(
                call=call, reviewer=self.qa_one, team_leader=self.team_leader,
                status=Review.Status.COMPLETED, completed_at=timezone.now(),
                evaluation_type=scope, score=final, scorecard_score=raw,
                scores=scores if raw == 100 else {}, critical_errors=errors,
                leader_status=Review.LeaderStatus.CLOSED if scope == "zero_defect" else Review.LeaderStatus.PENDING,
            )
        analytics = _summary(Review.objects.all())
        self.assertEqual(analytics["scored"], 3)
        self.assertEqual(analytics["average_score"], 26.67)
        self.assertEqual(analytics["below_85"], 3)
        self.assertEqual(analytics["critical_error_reviews"], 2)
        assignment = QAProjectAssignment.objects.get(qa=self.qa_one)
        users = [self.qa_one, self.team_leader]
        for role in (User.Role.PROJECT_MANAGER, User.Role.SUPERVISOR):
            user = User.objects.create_user(email=f"zero-score-{role}@example.com",
                                           first_name="Score", last_name="Reviewer", role=role,
                                           company=self.branch.company, branch=self.branch,
                                           must_change_password=False)
            if role == User.Role.PROJECT_MANAGER:
                QAProjectAssignment.objects.create(qa=user, dialer_campaign=assignment.dialer_campaign)
            users.append(user)
        for user in users:
            with self.subTest(role=user.role):
                self.client.force_login(user)
                summary = self.client.get(reverse("review-report-summary"))
                self.assertEqual(summary.status_code, 200, summary.content)
                self.assertEqual(summary.json()["average_score"], 26.67)
                self.assertEqual(summary.json()["trend"][-1]["average_score"], 26.67)
                reports = self.client.get(reverse("review-report-list"), {
                    "critical": "true", "score_state": "scored",
                    "score_rules": json.dumps([{"scope": "total", "operator": "eq", "value": 0}]),
                })
                self.assertEqual(reports.status_code, 200, reports.content)
                self.assertEqual(reports.json()["count"], 2)
                self.assertTrue(all(row["score"] == "0.00" for row in reports.json()["results"]))
                if user.role in (User.Role.PROJECT_MANAGER, User.Role.SUPERVISOR):
                    performance = self.client.get(reverse("project-performance"))
                    self.assertEqual(performance.status_code, 200, performance.content)
                    self.assertEqual(performance.json()["metrics"]["scored"], 3)
                    self.assertEqual(performance.json()["metrics"]["average_score"], 26.67)
                    self.assertEqual(performance.json()["metrics"]["below_benchmark"], 3)
                    self.assertEqual(performance.json()["trend"][-1]["average_score"], 26.67)
                    self.assertEqual(performance.json()["teams"][0]["average_score"], 26.67)
                    self.assertEqual(get_qa_overview(user=user)["metrics"]["average_score"], 26.67)


@override_settings(DIALER_CREDENTIAL_KEY=Fernet.generate_key().decode())
class CriticalScoreMigrationTests(TransactionTestCase):
    def test_backfill_preserves_original_scores_evidence_and_workflow_and_is_reversible(self):
        executor = MigrationExecutor(connection)
        latest = executor.loader.graph.leaf_nodes()
        previous = [("calls", "0017_critical_is_evaluable")]
        executor.migrate(previous)
        try:
            fixtures.AnalysisReservationTests.setUp(self)
            OldReview = executor.loader.project_state(previous).apps.get_model("calls", "Review")
            snapshots = []
            for index, (scope, score, critical, status) in enumerate((
                ("full", 100, True, "completed"),
                ("partial", None, True, "completed"),
                ("full", 88, False, "completed"),
                ("not_evaluable", None, False, "completed"),
                ("zero_defect", None, False, "completed"),
                ("partial", 74, True, "in_progress"),
                ("full", 90, True, "disputed"),
            )):
                call = self.call if index == 0 else CallEvent.objects.create(
                    dialer=self.dialer, branch=self.branch, event_key=f"score-migration-{index}".ljust(64, "0"))
                review = OldReview.objects.create(
                    call_id=call.pk, reviewer_id=self.qa_one.pk, team_leader_id=self.team_leader.pk,
                    evaluation_type=scope, status=status, score=score, completed_at=timezone.now(),
                    scores=fixtures.AnalysisReservationTests.full_scores(self) if score == 100 else {},
                    critical_errors=["misrepresentation"] if critical else [],
                    critical_error_evidence={"misrepresentation": {"comment": "Preserve evidence", "patches": []}} if critical else {},
                    scorecard_snapshot=scorecard_payload(), leader_status="acknowledged",
                    feedback_summary="Keep feedback", revision_count=2,
                )
                snapshots.append(OldReview.objects.filter(pk=review.pk).values().get())
            event = ReviewWorkflowEvent.objects.create(review_id=snapshots[0]["id"], actor=self.team_leader,
                                                       event_type="note_added", note="Keep history")
            notification = SystemNotification.objects.create(
                call=self.call, category="qa_report_ready", dedupe_key="score-migration-notification",
                title="QA report ready", message="Keep notification", metadata={"review_id": str(snapshots[0]["id"])})
            notification.recipients.add(self.team_leader)
            original_notification = SystemNotification.objects.filter(pk=notification.pk).values().get()
            MigrationExecutor(connection).migrate(latest)
            for original in snapshots:
                result = Review.objects.filter(pk=original["id"]).values().get()
                expected = {**original, "scorecard_score": original["score"]}
                if original["critical_errors"]:
                    expected["score"] = Decimal("0.00")
                self.assertEqual(result, expected)
            self.assertEqual(ReviewWorkflowEvent.objects.get(pk=event.pk).note, "Keep history")
            self.assertEqual(SystemNotification.objects.filter(pk=notification.pk).values().get(), original_notification)
            self.assertEqual(list(notification.recipients.values_list("pk", flat=True)), [self.team_leader.pk])
            MigrationExecutor(connection).migrate(previous)
            for original in snapshots:
                self.assertEqual(OldReview.objects.filter(pk=original["id"]).values().get(), original)
        finally:
            MigrationExecutor(connection).migrate(latest)
