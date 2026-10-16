#!/usr/bin/env python
"""
Test script to debug agent filtering issue
Run: python debug_agents.py
"""

import os
import sys
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.development')
django.setup()

from apps.accounts.models import User
from apps.agents.models import AgentProfile
from apps.agents import selectors

print("=" * 70)
print("AGENT FILTERING DEBUG")
print("=" * 70)
print()

# Check total agents
print("1. Checking all agents in database...")
print("-" * 70)
all_agents = User.objects.filter(role='agent', is_active=True)
print(f"Total active agent users: {all_agents.count()}")

agents_with_profile = all_agents.filter(agent_profile__isnull=False)
print(f"Agents with profile: {agents_with_profile.count()}")
print()

if agents_with_profile.count() == 0:
    print("⚠ No agents with profiles found in database!")
    print()
    print("To test, create an agent:")
    print("1. Register as agent in frontend")
    print("2. Or use Django admin to create one")
    sys.exit(0)

# Check verification statuses
print("2. Checking verification statuses...")
print("-" * 70)
for status_code, status_label in AgentProfile.VerificationStatus.choices:
    count = AgentProfile.objects.filter(verification_status=status_code).count()
    print(f"{status_label:12} ({status_code:12}): {count} agents")
print()

# Test the selector
print("3. Testing agent_profiles() selector...")
print("-" * 70)
agent_qs = selectors.agent_profiles()
print(f"Total from selector: {agent_qs.count()}")
print()

# Test filtering by verified status
print("4. Testing filter for 'verified' agents...")
print("-" * 70)
verified_filter = agent_qs.filter(agent_profile__verification_status='verified')
print(f"Query: agent_profiles().filter(agent_profile__verification_status='verified')")
print(f"Count: {verified_filter.count()}")
print()

if verified_filter.count() > 0:
    print("Verified agents:")
    for agent in verified_filter[:5]:
        print(f"  - {agent.name} ({agent.email})")
        print(f"    Agency: {agent.agent_profile.agency}")
        print(f"    Status: {agent.agent_profile.verification_status}")
        print(f"    Trust Score: {agent.agent_profile.trust_score}")
        print()
else:
    print("⚠ No verified agents found!")
    print()
    print("Current agent statuses:")
    for agent in agent_qs[:5]:
        print(f"  - {agent.name}")
        print(f"    Status: {agent.agent_profile.verification_status}")
        print(f"    Agency: {agent.agent_profile.agency or '(not set)'}")
        print()

# Test the actual view logic
print("5. Simulating the view filter logic...")
print("-" * 70)
status = 'verified'
qs = selectors.agent_profiles()
if status:
    filtered_qs = qs.filter(agent_profile__verification_status=status)
    print(f"Filtering by status='{status}'")
    print(f"Result count: {filtered_qs.count()}")
    print()

# Test SQL query
print("6. Generated SQL query...")
print("-" * 70)
print(filtered_qs.query)
print()

# Summary
print("=" * 70)
print("SUMMARY")
print("=" * 70)

if verified_filter.count() == 0:
    print("❌ Problem: No verified agents in database")
    print()
    print("Solution:")
    print("1. Create agent user (register as agent)")
    print("2. Admin verifies agent:")
    print("   - Go to /admin/agents/agentprofile/")
    print("   - Change verification_status to 'verified'")
    print("   - Or use API: POST /admin/verifications/{agent_id}")
    print()
    print("OR for testing, manually update:")
    print("python manage.py shell")
    print(">>> from apps.agents.models import AgentProfile")
    print(">>> AgentProfile.objects.update(verification_status='verified')")
else:
    print("✅ Filter is working correctly!")
    print(f"Found {verified_filter.count()} verified agents")
    print()
    print("If frontend shows empty, check:")
    print("1. API URL is correct: /api/v1/agents?verificationStatus=verified")
    print("2. Network tab shows 200 response with data")
    print("3. Frontend is parsing response correctly")

print()
