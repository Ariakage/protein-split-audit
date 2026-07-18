# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from protein_split_audit.analysis.robustness import sign_concordance


def test_class_balance_sign_concordance_is_descriptive() -> None:
    same = sign_concordance(
        accuracy=0.1,
        balanced_accuracy=0.02,
        macro_f1=0.3,
    )
    mixed = sign_concordance(
        accuracy=0.1,
        balanced_accuracy=-0.02,
        macro_f1=0.0,
    )

    assert same.signs_agree is True
    assert same.direction == "positive"
    assert mixed.signs_agree is False
    assert mixed.direction == "mixed"
