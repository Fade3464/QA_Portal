"""Scheduled externally (cron/operator) until administrative routine scheduling is built."""
from datetime import timedelta
from django.core.management.base import BaseCommand
from django.utils import timezone
from apps.ai_assistant.models import AIConversation, AIToolAudit


class Command(BaseCommand):
    help = 'Remove expired AI conversations and metadata-only tool audit records.'

    def add_arguments(self, parser):
        parser.add_argument('--days', type=int, default=30, help='Conversation retention days (1-365).')
        parser.add_argument('--audit-days', type=int, default=90, help='Tool audit retention days (1-365).')

    def handle(self, *args, **options):
        days, audit_days = options['days'], options['audit_days']
        if not 1 <= days <= 365 or not 1 <= audit_days <= 365:
            raise ValueError('Retention days must be between 1 and 365.')
        conversations, _ = AIConversation.objects.filter(
            updated_at__lt=timezone.now() - timedelta(days=days)
        ).delete()
        audits, _ = AIToolAudit.objects.filter(
            created_at__lt=timezone.now() - timedelta(days=audit_days)
        ).delete()
        self.stdout.write(f'Pruned {conversations} conversation/related rows and {audits} audit rows.')
