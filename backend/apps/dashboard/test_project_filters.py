import json
from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.calls.models import CallEvent, Review
from apps.tenancy.models import (
    Branch,
    Company,
    Dialer,
    DialerCampaign,
    QAProjectAssignment,
    Team,
)


class MultiProjectPerformanceTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Multi", slug="multi")
        self.branch = Branch.objects.create(
            company=self.company, name="Main", code="MAIN"
        )
        self.reviewer = self.make_user("qa", User.Role.QA)
        self.manager = self.make_user("manager", User.Role.PROJECT_MANAGER)
        self.supervisor = self.make_user("supervisor", User.Role.SUPERVISOR)
        self.team = Team.objects.create(
            branch=self.branch,
            name="Multi Team",
            team_leader=self.make_user("leader", User.Role.TEAM_LEADER),
        )
        self.projects = []
        self.reports = []
        for dialer_index, scores in enumerate(((90, 40), (30, 60))):
            dialer = Dialer.objects.create(
                branch=self.branch,
                name=f"Dialer {dialer_index}",
                api_url="https://dialer.example.com",
                api_username="api",
            )
            for name, score in zip(("Alpha", "Beta"), scores):
                mapping = DialerCampaign.objects.create(
                    dialer=dialer, campaign=name, project_name=name
                )
                self.projects.append(mapping)
                QAProjectAssignment.objects.create(
                    qa=self.manager, dialer_campaign=mapping
                )
                call = CallEvent.objects.create(
                    dialer=dialer,
                    branch=self.branch,
                    team=self.team,
                    event_key=f"multi-{mapping.pk}".ljust(64, "0"),
                    campaign=name,
                    event_type=CallEvent.EventType.DISPOSITION,
                    agent_name="Agent",
                )
                self.reports.append(
                    Review.objects.create(
                        call=call,
                        reviewer=self.reviewer,
                        status=Review.Status.COMPLETED,
                        score=score,
                        completed_at=timezone.now(),
                        critical_errors=["privacy_violation"] if score == 60 else [],
                    )
                )
        hidden_branch = Branch.objects.create(
            company=self.company, name="Hidden", code="HIDDEN"
        )
        hidden_dialer = Dialer.objects.create(
            branch=hidden_branch,
            name="Hidden",
            api_url="https://dialer.example.com",
            api_username="api",
        )
        self.hidden = DialerCampaign.objects.create(
            dialer=hidden_dialer, campaign="Alpha", project_name="Alpha"
        )
        self.url = reverse("project-performance")

    def make_user(self, name, role):
        return User.objects.create(
            email=f"{name}@example.com",
            first_name=name,
            last_name="Test",
            password="!unusable",
            role=role,
            company=self.company,
            branch=self.branch,
            must_change_password=False,
        )

    def pair(self, mapping):
        return {"dialer": str(mapping.dialer_id), "project": mapping.project_name}

    def test_union_preserves_dialer_pairs_for_both_roles_and_all_metrics(self):
        selections = [self.pair(self.projects[0]), self.pair(self.projects[3])]
        for user in (self.manager, self.supervisor):
            with self.subTest(role=user.role):
                self.client.force_login(user)
                response = self.client.post(
                    self.url,
                    {"days": 1, "projects": selections},
                    content_type="application/json",
                )
                self.assertEqual(response.status_code, 200, response.content)
                payload = response.json()
                self.assertEqual(payload["selected_projects"], selections)
                self.assertEqual(payload["metrics"]["evaluated"], 2)
                self.assertEqual(payload["metrics"]["average_score"], 75)
                self.assertEqual(payload["metrics"]["critical"], 1)
                self.assertEqual(payload["metrics"]["below_benchmark"], 1)
                self.assertEqual(sum(row["evaluated"] for row in payload["trend"]), 2)
                # Available choices stay complete even when reports are filtered.
                self.assertEqual(len(payload["project_groups"]), 2)
                self.assertEqual(sum(row["evaluated"] for row in payload["teams"]), 2)
                get_response = self.client.get(
                    self.url, {"days": 1, "projects": json.dumps(selections)}
                )
                self.assertEqual(get_response.json()["metrics"], payload["metrics"])

    def test_duplicates_clear_empty_results_and_single_filter_compatibility(self):
        self.client.force_login(self.manager)
        pair = self.pair(self.projects[0])
        response = self.client.post(
            self.url, {"projects": [pair, pair]}, content_type="application/json"
        )
        self.assertEqual(response.json()["selected_projects"], [pair])
        self.assertEqual(response.json()["metrics"]["evaluated"], 1)
        single = self.client.get(
            self.url, {"project": pair["project"], "dialer": pair["dialer"]}
        )
        self.assertEqual(single.json()["metrics"], response.json()["metrics"])
        for payload in ({}, {"projects": []}):
            cleared = self.client.post(
                self.url, payload, content_type="application/json"
            )
            self.assertEqual(cleared.json()["metrics"]["evaluated"], 4)
        self.reports[0].completed_at = timezone.now() - timedelta(days=100)
        self.reports[0].save(update_fields=["completed_at"])
        empty = self.client.post(
            self.url, {"projects": [pair]}, content_type="application/json"
        )
        self.assertEqual(empty.json()["metrics"]["evaluated"], 0)
        self.assertIsNone(empty.json()["metrics"]["average_score"])

    def test_every_pair_must_be_accessible_and_revoked_assignments_fail_closed(self):
        self.client.force_login(self.manager)
        valid = self.pair(self.projects[0])
        for invalid in (
            self.pair(self.hidden),
            {"dialer": valid["dialer"], "project": "Unassigned"},
            {"dialer": "not-a-uuid", "project": "Alpha"},
        ):
            with self.subTest(invalid=invalid):
                result = self.client.post(
                    self.url,
                    {"projects": [valid, invalid]},
                    content_type="application/json",
                )
                self.assertEqual(result.status_code, 400)
        QAProjectAssignment.objects.filter(
            qa=self.manager, dialer_campaign=self.projects[0]
        ).delete()
        self.assertEqual(
            self.client.post(
                self.url, {"projects": [valid]}, content_type="application/json"
            ).status_code,
            400,
        )
        self.client.force_login(self.supervisor)
        self.assertEqual(
            self.client.post(
                self.url, {"projects": [valid]}, content_type="application/json"
            ).status_code,
            200,
        )
        self.assertEqual(
            self.client.post(
                self.url,
                {"projects": [self.pair(self.hidden)]},
                content_type="application/json",
            ).status_code,
            400,
        )

    def test_malformed_large_and_ambiguous_requests_return_validation_errors(self):
        self.client.force_login(self.manager)
        pair = self.pair(self.projects[0])
        malformed = [
            None,
            {},
            "not-json",
            [None],
            ["Alpha"],
            [{"dialer": [], "project": "Alpha"}],
            [{**pair, "extra": True}],
            [pair] * 201,
        ]
        for selections in malformed:
            with self.subTest(selections_type=type(selections).__name__):
                self.assertEqual(
                    self.client.post(
                        self.url,
                        {"projects": selections},
                        content_type="application/json",
                    ).status_code,
                    400,
                )
        for days in (None, True, 1.5, 0, 365, "invalid"):
            with self.subTest(days=days):
                self.assertEqual(
                    self.client.post(
                        self.url, {"days": days}, content_type="application/json"
                    ).status_code,
                    400,
                )
        self.assertEqual(
            self.client.get(
                self.url, {"projects": json.dumps([pair]), "dialer": pair["dialer"]}
            ).status_code,
            400,
        )
        self.assertEqual(
            self.client.get(self.url, {"projects": ["[]", "[]"]}).status_code, 400
        )
        self.assertEqual(
            self.client.get(self.url, {"projects": " " * 64_001}).status_code, 400
        )

    def test_zero_defect_reports_count_without_affecting_numeric_average(self):
        self.client.force_login(self.manager)
        report = self.reports[0]
        report.evaluation_type = Review.EvaluationType.ZERO_DEFECT
        report.score = None
        report.save()
        result = self.client.post(
            self.url,
            {"projects": [self.pair(self.projects[0]), self.pair(self.projects[3])]},
            content_type="application/json",
        )
        self.assertEqual(result.status_code, 200, result.content)
        self.assertEqual(result.json()["metrics"]["evaluated"], 2)
        self.assertEqual(result.json()["metrics"]["scored"], 1)
        self.assertEqual(result.json()["metrics"]["average_score"], 60)

    def test_other_roles_cannot_query_management_performance(self):
        self.client.force_login(self.reviewer)
        self.assertEqual(
            self.client.post(
                self.url, {"projects": []}, content_type="application/json"
            ).status_code,
            403,
        )
