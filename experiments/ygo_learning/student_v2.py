"""Versioned P1 student: categorical identities plus actual numeric resources."""
import torch
from torch import nn
from student import ByteFields

KEYS=('cards','card_numeric','global','global_numeric','history','chains','actions','action_numeric','members','legal')


class StudentV2(nn.Module):
    def __init__(self):
        super().__init__()
        self.card_fields=ByteFields(41,2)
        self.card_encoder=nn.Sequential(nn.Linear(90,16),nn.GELU())
        self.global_fields=ByteFields(23,2)
        self.history_fields=ByteFields(29,2)
        self.chain_fields=ByteFields(22,2)
        self.state=nn.Sequential(nn.Linear(160*16+46+16+32*58+16*44,256),nn.GELU(),nn.LayerNorm(256))
        self.action=nn.Sequential(ByteFields(27,4),nn.Linear(108,64),nn.GELU())
        self.score=nn.Sequential(nn.Linear(256+64+16+8,128),nn.GELU(),nn.Linear(128,1))

    def forward(self,cards,card_numeric,global_state,global_numeric,history,chains,actions,action_numeric,members,legal):
        card=self.card_encoder(torch.cat((self.card_fields(cards),card_numeric),dim=-1))
        state=self.state(torch.cat((card.flatten(1),self.global_fields(global_state),global_numeric,
                                    self.history_fields(history).flatten(1),self.chain_fields(chains).flatten(1)),dim=-1))
        chosen=torch.bmm(members,card)/members.sum(-1,keepdim=True).clamp_min(1)
        scores=self.score(torch.cat((state[:,None,:].expand(-1,actions.shape[1],-1),
                                     self.action(actions),chosen,action_numeric),dim=-1)).squeeze(-1)
        return scores.masked_fill(~legal,-1e9)
