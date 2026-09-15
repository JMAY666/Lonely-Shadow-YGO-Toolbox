'use strict';

// The same saved presentation is used by all three deck libraries.
function updateDeckRepresentatives() {
  const button=$('#deck-representatives-button');
  button.disabled=app.busy;
  button.textContent=`代表卡设置 · ${validDeckRepresentatives().filter(Boolean).length}/3`;
}
const deckAppearance = {slot:0,cards:[null,null,null]};
function renderDeckAppearance() {
  $('#representative-slots').innerHTML = deckAppearance.cards.map((code,index)=>`<button type="button" data-representative-slot="${index}" aria-label="代表卡 ${index+1}" aria-pressed="${index===deckAppearance.slot}">${code?`<img src="/pics/${code}.jpg" alt="${escape(app.cache.get(code)?.name||code)}">`:'＋'}<small>${index+1}</small></button>`).join('');
  $('#representative-cards').innerHTML = [...new Set(zones.flatMap(zone=>app.deck[zone]))].map(code=>`<button type="button" data-representative-card="${code}" aria-label="${escape(app.cache.get(code)?.name||code)}"><img src="/pics/${code}.jpg" alt="${escape(app.cache.get(code)?.name||code)}" loading="lazy"></button>`).join('');
}
$('#deck-representatives-button').onclick = () => {
  if(app.busy)return;
  deckAppearance.slot=0;deckAppearance.cards=validDeckRepresentatives();
  renderDeckAppearance();$('#deck-appearance-dialog').showModal();
};
$('#deck-appearance-dialog').onclick = event => {
  const button=event.target.closest('button');if(!button)return;
  if(button.dataset.representativeSlot!==undefined)deckAppearance.slot=Number(button.dataset.representativeSlot);
  else if(button.dataset.representativeCard) {
    deckAppearance.cards[deckAppearance.slot]=Number(button.dataset.representativeCard);
    deckAppearance.slot=Math.min(2,deckAppearance.slot+1);
  } else if(button.id==='representative-clear')deckAppearance.cards[deckAppearance.slot]=null;
  else if(button.id==='representative-cancel')return $('#deck-appearance-dialog').close();
  else if(button.id==='representative-apply') {
    setDeckRepresentatives(deckAppearance.cards);dirty();updateDeckRepresentatives();
    return $('#deck-appearance-dialog').close();
  }
  renderDeckAppearance();
};
