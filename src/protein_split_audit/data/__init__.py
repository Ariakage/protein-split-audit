# SPDX-License-Identifier: Apache-2.0

"""Source-data acquisition APIs."""

from protein_split_audit.data.download_uniprot import (
    DownloadError,
    DownloadResult,
    download_uniprot,
)

__all__ = ["DownloadError", "DownloadResult", "download_uniprot"]
