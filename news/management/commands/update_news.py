from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Collect news, group articles into stories, summarise pending stories."

    def handle(self, *args, **options):
        failures = []

        steps = [
            ("[1/3] Collecting new articles", "collect_news", {}),
            ("[2/3] Grouping articles into stories", "backfill_stories", {}),
            ("[3/3] Processing pending stories", "process_stories", {"limit": 20}),
        ]

        self.stdout.write(self.style.SUCCESS("=== Clarion AI News Update ==="))

        for label, command, kwargs in steps:
            self.stdout.write(f"\n{label}...")
            try:
                call_command(command, **kwargs)
            except Exception as error:
                # One failing step must not stop the later ones.
                failures.append(f"{command}: {error}")
                self.stderr.write(self.style.ERROR(f"{command} failed: {error}"))

        if failures:
            # Non-zero exit code so Task Scheduler / cron can show the failure.
            raise CommandError("Update finished with errors: " + "; ".join(failures))

        self.stdout.write(self.style.SUCCESS("\n=== News update completed ==="))
