# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations


def test_majority_uses_lexicographic_tie_break() -> None:
    from protein_split_audit.models.majority import fit_majority

    model = fit_majority(["2.7", "1.1", "2.7", "1.1"])

    assert model.label == "1.1"
    assert model.counts == (("1.1", 2), ("2.7", 2))
    assert model.predict(3) == ("1.1", "1.1", "1.1")
