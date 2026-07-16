# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from pathlib import Path

import torch
from transformers import EsmConfig, EsmForMaskedLM

from protein_split_audit.embeddings.model_registry import load_local_esm_model


def test_tiny_local_esm_loads_without_network_and_exposes_encoder(tmp_path: Path) -> None:
    torch.manual_seed(42)
    config = EsmConfig(
        vocab_size=12,
        hidden_size=8,
        num_hidden_layers=1,
        num_attention_heads=2,
        intermediate_size=16,
        max_position_embeddings=32,
        pad_token_id=1,
        mask_token_id=4,
        token_dropout=False,
    )
    model = EsmForMaskedLM(config)
    model.save_pretrained(tmp_path, safe_serialization=True)

    loaded = load_local_esm_model(
        tmp_path,
        device="cpu",
        intraop_threads=8,
        interop_threads=1,
        deterministic_algorithms=True,
    )
    input_ids = torch.tensor([[0, 5, 6, 2, 1]], dtype=torch.long)
    attention_mask = torch.tensor([[1, 1, 1, 1, 0]], dtype=torch.long)
    with torch.inference_mode():
        output = loaded.encoder(input_ids=input_ids, attention_mask=attention_mask)

    assert tuple(output.last_hidden_state.shape) == (1, 5, 8)
    assert loaded.full_model.training is False
    assert all(not parameter.requires_grad for parameter in loaded.full_model.parameters())
    assert loaded.loading_info == {
        "error_msgs": [],
        "mismatched_keys": [],
        "missing_keys": [],
        "unexpected_keys": [],
    }
