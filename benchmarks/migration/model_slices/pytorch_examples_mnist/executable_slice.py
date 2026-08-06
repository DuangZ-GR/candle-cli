"""Executable MNIST classifier-head slice derived from ``Net.forward``.

The frozen upstream file remains byte-for-byte unchanged in ``upstream_main.py``.
This small functional adapter replaces the 9,216-feature convolution output with
a fixed four-feature synthetic tensor, while preserving the upstream sequence of
two linear projections with a ReLU between them.  The adapter exists so the
migration benchmark is deterministic, offline, CPU-friendly, and independent of
the MNIST dataset and torchvision.

This file is counted as one explicit manual adaptation.  Its PyTorch API calls
are then migrated by candle-cli itself; the target runtime imports the rewritten
same file rather than a separately maintained MindSpore implementation.
"""

import torch


def mnist_classifier_head(x, weight1, bias1, weight2, bias2):
    """Run the two dense layers and intervening ReLU from the MNIST example."""

    hidden = torch.matmul(x, weight1)
    hidden = torch.add(hidden, bias1)
    hidden = torch.nn.functional.relu(hidden)
    logits = torch.matmul(hidden, weight2)
    return torch.add(logits, bias2)
