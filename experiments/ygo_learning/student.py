"""Small action-ranking student for hardware validation, not a shipped policy."""
import torch
from torch import nn


class ByteFields(nn.Module):
    """The upstream byte columns encode categories, not a shared scalar scale."""
    def __init__(self, fields, channels):
        super().__init__()
        self.values = nn.Embedding(fields * 256, channels)
        self.register_buffer('offsets', torch.arange(fields) * 256)

    def forward(self, value):
        indices = (value * 255).round().long().clamp(0, 255) + self.offsets
        return self.values(indices).flatten(-2)


class Student(nn.Module):
    def __init__(self):
        super().__init__()
        self.cards = nn.Sequential(ByteFields(41, 2), nn.Linear(82, 16), nn.GELU())
        self.global_fields = ByteFields(23, 2)
        self.history_fields = ByteFields(14, 2)
        self.state = nn.Sequential(nn.Linear(160 * 16 + 46 + 32 * 28, 256),
                                   nn.GELU(), nn.LayerNorm(256))
        self.action = nn.Sequential(ByteFields(12, 8), nn.Linear(96, 64), nn.GELU())
        self.score = nn.Sequential(nn.Linear(320, 128), nn.GELU(), nn.Linear(128, 1))

    def forward(self, cards, global_state, history, actions, legal):
        card_features = self.cards(cards).flatten(1)
        state = self.state(torch.cat((card_features, self.global_fields(global_state),
                                     self.history_fields(history).flatten(1)), dim=-1))
        action = self.action(actions)
        state = state[:, None, :].expand(-1, actions.shape[1], -1)
        scores = self.score(torch.cat((state, action), dim=-1)).squeeze(-1)
        return scores.masked_fill(~legal, -1e9)
