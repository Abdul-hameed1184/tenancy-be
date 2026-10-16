"""
Simple Python script to verify all agents.
Run directly without Django: python verify_agents_simple.py
"""
import psycopg2
import os

# Database connection from .env
DB_URL = os.getenv('DATABASE_URL', 'postgres://pleet:pleet_dev_password@localhost:5433/pleet')

print("=" * 70)
print("AGENT VERIFICATION SCRIPT")
print("=" * 70)
print()

try:
    # Connect to database
    conn = psycopg2.connect(DB_URL)
    cursor = conn.cursor()

    # Check current agents
    cursor.execute("""
        SELECT
            u.name, u.email, ap.verification_status, ap.agency
        FROM agents_agentprofile ap
        JOIN accounts_user u ON ap.user_id = u.id
        WHERE u.is_active = true
    """)

    agents = cursor.fetchall()

    print(f"Found {len(agents)} agents:")
    print("-" * 70)

    if not agents:
        print("No agents found in database!")
        print()
        print("Create an agent user first:")
        print("1. Register as agent in frontend")
        print("2. Or use Django admin")
        conn.close()
        input("\nPress Enter to exit...")
        exit(0)

    for name, email, status, agency in agents:
        print(f"  • {name} ({email})")
        print(f"    Status: {status}")
        print(f"    Agency: {agency or '(not set)'}")
        print()

    # Count unverified
    cursor.execute("""
        SELECT COUNT(*) FROM agents_agentprofile
        WHERE verification_status IN ('unverified', 'pending')
    """)
    unverified_count = cursor.fetchone()[0]

    print(f"Agents needing verification: {unverified_count}")
    print()

    if unverified_count == 0:
        print("✓ All agents are already verified!")
        conn.close()
        input("\nPress Enter to exit...")
        exit(0)

    # Ask for confirmation
    response = input("Verify all agents? (yes/no): ").strip().lower()

    if response != 'yes':
        print("Cancelled.")
        conn.close()
        input("\nPress Enter to exit...")
        exit(0)

    # Update to verified
    cursor.execute("""
        UPDATE agents_agentprofile
        SET verification_status = 'verified'
        WHERE verification_status IN ('unverified', 'pending')
    """)

    conn.commit()
    updated = cursor.rowcount

    print()
    print("=" * 70)
    print(f"✓ SUCCESS! Verified {updated} agents")
    print("=" * 70)
    print()

    # Show updated agents
    cursor.execute("""
        SELECT
            u.name, u.email, ap.verification_status, ap.agency
        FROM agents_agentprofile ap
        JOIN accounts_user u ON ap.user_id = u.id
        WHERE u.is_active = true
    """)

    agents = cursor.fetchall()

    print("Updated agents:")
    print("-" * 70)
    for name, email, status, agency in agents:
        print(f"  • {name} ({email})")
        print(f"    Status: {status}")
        print(f"    Agency: {agency or '(not set)'}")
        print()

    cursor.close()
    conn.close()

    print("Next steps:")
    print("1. Refresh your frontend browser")
    print("2. Open Assign Agent dialog")
    print("3. Agent names should now appear!")
    print()

except psycopg2.Error as e:
    print(f"Database error: {e}")
    print()
    print("Make sure:")
    print("1. PostgreSQL is running")
    print("2. DATABASE_URL in .env is correct")
    print("3. Database has agents table")

except Exception as e:
    print(f"Error: {e}")

input("\nPress Enter to exit...")
