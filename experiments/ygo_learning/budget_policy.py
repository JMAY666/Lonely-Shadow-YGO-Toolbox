"""Approved resource gates for the repaired P2/P3 validation run.

The policy is versioned so historical two-hour/four-hour reports and their
registration remain auditable and immutable.
"""
import math

BUDGET_POLICY_ID = 'p3-v8-approved-20260921'
WORKER_LIMIT_SECONDS = 3 * 60 * 60
FAMILY_TIME_LIMIT_HOURS = 5
FAMILY_DISK_LIMIT_GIB = 20
REGISTRATION_FILENAME = 'validation-registration-v8.json'


def manifest():
    return {
        'id': BUDGET_POLICY_ID,
        'worker_limit_seconds': WORKER_LIMIT_SECONDS,
        'family_time_limit_hours': FAMILY_TIME_LIMIT_HOURS,
        'family_disk_limit_GiB': FAMILY_DISK_LIMIT_GIB,
        'registration_filename': REGISTRATION_FILENAME,
    }


def legacy_manifest():
    return {
        'id': 'p3-v1-original',
        'worker_limit_seconds': 7200,
        'family_time_limit_hours': 4,
        'family_disk_limit_GiB': 20,
        'registration_filename': 'validation-registration.json',
    }


def finite_positive(value):
    return (not isinstance(value, bool) and isinstance(value, (int, float))
            and math.isfinite(value) and value > 0)
