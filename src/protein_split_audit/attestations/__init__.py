# SPDX-License-Identifier: Apache-2.0

"""Fail-closed authorization types for the frozen v0.5 Test protocol."""

from protein_split_audit.attestations.test_access import (
    FormalRuntimeIdentity,
    TestFreezeAttestation,
    VerifiedTestAuthorization,
    verify_test_authorization,
)

__all__ = [
    "FormalRuntimeIdentity",
    "TestFreezeAttestation",
    "VerifiedTestAuthorization",
    "verify_test_authorization",
]
