"""
Django management command to verify all agents.
Usage: python manage.py verify_all_agents
"""
from django.core.management.base import BaseCommand
from apps.agents.models import AgentProfile


class Command(BaseCommand):
    help = 'Mark all unverified/pending agents as verified (for testing)'

    def handle(self, *args, **options):
        self.stdout.write('=' * 70)
        self.stdout.write('VERIFYING ALL AGENTS')
        self.stdout.write('=' * 70)
        self.stdout.write('')

        # Count current agents
        total = AgentProfile.objects.count()
        unverified = AgentProfile.objects.filter(
            verification_status__in=['unverified', 'pending']
        ).count()

        self.stdout.write(f'Total agents: {total}')
        self.stdout.write(f'Unverified/Pending: {unverified}')
        self.stdout.write('')

        if unverified == 0:
            self.stdout.write(self.style.SUCCESS('All agents are already verified!'))
            self.stdout.write('')
            self._show_agents()
            return

        # Verify all
        updated = AgentProfile.objects.filter(
            verification_status__in=['unverified', 'pending']
        ).update(verification_status='verified')

        self.stdout.write(self.style.SUCCESS(f'✓ Verified {updated} agents'))
        self.stdout.write('')

        # Show all agents
        self._show_agents()

        self.stdout.write('')
        self.stdout.write('=' * 70)
        self.stdout.write(self.style.SUCCESS('SUCCESS!'))
        self.stdout.write('=' * 70)
        self.stdout.write('')
        self.stdout.write('Next steps:')
        self.stdout.write('1. Refresh your frontend browser')
        self.stdout.write('2. Open Assign Agent dialog')
        self.stdout.write('3. Agent names should now appear!')
        self.stdout.write('')

    def _show_agents(self):
        self.stdout.write('Current agents:')
        self.stdout.write('-' * 70)

        agents = AgentProfile.objects.select_related('user').all()

        if not agents:
            self.stdout.write('  (No agents found)')
            return

        for profile in agents:
            name = profile.user.name or '(no name)'
            email = profile.user.email
            status = profile.verification_status
            agency = profile.agency or '(no agency)'

            self.stdout.write(f'  • {name} ({email})')
            self.stdout.write(f'    Status: {status}')
            self.stdout.write(f'    Agency: {agency}')
            self.stdout.write('')
