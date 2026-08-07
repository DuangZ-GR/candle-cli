import torch
import torch.nn.functional as F


def forward(x):
    values = torch.zeros((2, 3), dtype=torch.float32)
    return F.relu(torch.add(x, values)).reshape(3, 2)
