import os

from django.core.management.base import BaseCommand

from apps.accounts.models import User


class Command(BaseCommand):
    help = "Create the initial system administrator from environment variables if it does not exist."

    def handle(self, *args, **options):
        email = os.getenv("ADMIN_EMAIL", "").strip().lower()
        password = os.getenv("ADMIN_PASSWORD", "")
        if not email or not password:
            self.stdout.write(
                "ADMIN_EMAIL/ADMIN_PASSWORD not set; skipping administrator bootstrap"
            )
            return
        if User.objects.filter(email=email).exists():
            self.stdout.write("Administrator account already exists")
            return
        User.objects.create_superuser(
            email=email,
            password=password,
            first_name=os.getenv("ADMIN_FIRST_NAME", "System"),
            last_name=os.getenv("ADMIN_LAST_NAME", "Administrator"),
            must_change_password=True,
        )
        self.stdout.write(self.style.SUCCESS(f"Created administrator {email}"))
