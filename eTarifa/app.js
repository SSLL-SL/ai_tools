const exampleTariffs = [
  { id: 'flat-demo', name: 'Luz Sencilla', type: 'flat', energy: { flat: 0.145 }, powerPeak: 0.089, powerValley: 0.029, fee: 0 },
  { id: 'two-demo', name: 'Día y Noche', type: 'two', energy: { peak: 0.184, valley: 0.095 }, powerPeak: 0.105, powerValley: 0.031, fee: 0 },
  { id: 'three-demo', name: 'Ahorro 3 Periodos', type: 'three', energy: { peak: 0.214, flat: 0.132, valley: 0.082 }, powerPeak: 0.095, powerValley: 0.027, fee: 0 },
  { id: 'market-demo', name: 'Indexada Referencia', type: 'market', energy: { peak: 0.168, flat: 0.126, valley: 0.101 }, powerPeak: 0.105, powerValley: 0.031, fee: 0 },
];

let tariffs = [...exampleTariffs];
let editingTariffId = null;
const periodLabels = { peak: 'Punta', flat: 'Llano', valley: 'Valle' };
const typeLabels = { flat: 'Plana 24h', two: '2 periodos', three: '3 periodos', market: 'Mercado estimado' };
const inputIds = ['usage-peak', 'usage-flat', 'usage-valley', 'power-peak', 'power-valley'];
const money = new Intl.NumberFormat('es-ES', { style: 'currency', currency: 'EUR' });
const number = new Intl.NumberFormat('es-ES', { minimumFractionDigits: 2, maximumFractionDigits: 2 });

const getInput = (id) => Math.max(0, Number(document.getElementById(id).value) || 0);
const formatMoney = (value) => money.format(value);

function getCost(tariff) {
  const peak = getInput('usage-peak');
  const flat = getInput('usage-flat');
  const valley = getInput('usage-valley');
  let energyCost = 0;

  if (tariff.type === 'flat') {
    energyCost = (peak + flat + valley) * tariff.energy.flat;
  } else if (tariff.type === 'two') {
    energyCost = peak * tariff.energy.peak + (flat + valley) * tariff.energy.valley;
  } else {
    energyCost = peak * tariff.energy.peak + flat * tariff.energy.flat + valley * tariff.energy.valley;
  }

  const powerCost = (getInput('power-peak') * tariff.powerPeak + getInput('power-valley') * tariff.powerValley) * 30;
  return { energyCost, powerCost, fee: tariff.fee, total: energyCost + powerCost + tariff.fee };
}

function energyDescription(tariff) {
  if (tariff.type === 'flat') return `Todo el día ${number.format(tariff.energy.flat)} €/kWh`;
  if (tariff.type === 'two') return `Punta ${number.format(tariff.energy.peak)} · Valle ${number.format(tariff.energy.valley)}`;
  return `P ${number.format(tariff.energy.peak)} · L ${number.format(tariff.energy.flat)} · V ${number.format(tariff.energy.valley)}`;
}

function renderTariffs() {
  const ranked = tariffs.map((tariff) => ({ ...tariff, costs: getCost(tariff) })).sort((a, b) => a.costs.total - b.costs.total);
  const bestCost = ranked[0]?.costs.total ?? 0;
  const nextCost = ranked[1]?.costs.total ?? bestCost;
  const saving = Math.max(0, nextCost - bestCost) * 12;

  const allExamples = tariffs.length > 0 && tariffs.every((item) => !item.custom);
  document.getElementById('tariff-count').textContent = `${tariffs.length} ${tariffs.length === 1 ? 'tarifa' : 'tarifas'}${allExamples ? ' de ejemplo' : ' comparadas'}`;
  document.getElementById('summary-title').textContent = ranked.length ? `${ranked[0].name} es la más económica` : 'Añade una tarifa para empezar';
  document.getElementById('summary-detail').textContent = ranked.length > 1
    ? `Te costaría ${formatMoney(bestCost)} al mes, antes de impuestos.`
    : 'Añade otra tarifa para ver cuánto puedes ahorrar.';
  document.getElementById('annual-saving').textContent = ranked.length > 1 ? formatMoney(saving) : '—';

  document.getElementById('tariff-list').innerHTML = ranked.map((tariff, index) => `
    <article class="tariff-card${index === 0 ? ' best' : ''}">
      <div class="tariff-actions">
        <button class="tariff-action edit-tariff" type="button" data-edit="${tariff.id}" aria-label="Editar ${escapeHtml(tariff.name)}" title="Editar tarifa">✎</button>
        <button class="tariff-action delete-tariff" type="button" data-remove="${tariff.id}" aria-label="Borrar ${escapeHtml(tariff.name)}" title="Borrar tarifa">×</button>
      </div>
      <div class="tariff-identity">
        <div class="tariff-label-row"><span class="tariff-type">${typeLabels[tariff.type]}</span>${index === 0 ? '<span class="best-badge">MEJOR PRECIO</span>' : ''}</div>
        <h3 class="tariff-name">${escapeHtml(tariff.name)}</h3>
      </div>
      <div class="tariff-breakdown">
        <div class="breakdown-item">ENERGÍA<strong>${formatMoney(tariff.costs.energyCost)}</strong></div>
        <div class="breakdown-item">POTENCIA<strong>${formatMoney(tariff.costs.powerCost)}</strong></div>
        ${tariff.fee ? `<div class="breakdown-item">CUOTA<strong>${formatMoney(tariff.fee)}</strong></div>` : ''}
        <div class="breakdown-item">PRECIO ENERGÍA<strong>${energyDescription(tariff)}</strong></div>
      </div>
      <div class="tariff-price"><strong>${formatMoney(tariff.costs.total)}</strong><span>al mes · antes de impuestos</span><div class="price-details">${formatMoney(tariff.costs.total * 12)} / año</div></div>
    </article>
  `).join('');

  document.querySelectorAll('[data-edit]').forEach((button) => {
    button.addEventListener('click', () => {
      const tariff = tariffs.find((item) => item.id === button.dataset.edit);
      if (tariff) openTariffDialog(tariff);
    });
  });

  document.querySelectorAll('[data-remove]').forEach((button) => {
    button.addEventListener('click', () => {
      tariffs = tariffs.filter((tariff) => tariff.id !== button.dataset.remove);
      renderTariffs();
    });
  });
}

function escapeHtml(value) {
  return value.replace(/[&<>"']/g, (character) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[character]);
}

function updateEnergyFields(type, energy = {}) {
  const fields = document.getElementById('energy-fields');
  const names = type === 'flat'
    ? [['flat', 'Todo el día', 0.145]]
    : type === 'two'
      ? [['peak', 'Punta', 0.184], ['valley', 'Valle (llano + valle)', 0.095]]
      : [['peak', 'Punta', type === 'three' ? 0.214 : 0.168], ['flat', 'Llano', type === 'three' ? 0.132 : 0.126], ['valley', 'Valle', type === 'three' ? 0.082 : 0.101]];
  fields.innerHTML = names.map(([key, label, defaultValue]) => {
    const value = energy[key] ?? defaultValue;
    return `<label class="form-label">${label}<input name="energy-${key}" type="number" min="0" step="0.001" required value="${value}" /></label>`;
  }).join('');
}

inputIds.forEach((id) => document.getElementById(id).addEventListener('input', renderTariffs));
const dialog = document.getElementById('tariff-dialog');
const tariffForm = document.getElementById('tariff-form');
const tariffType = document.getElementById('tariff-type');
const submitButton = tariffForm.querySelector('[type="submit"]');

function openTariffDialog(tariff = null) {
  editingTariffId = tariff?.id ?? null;
  tariffForm.reset();

  if (tariff) {
    document.getElementById('dialog-context').textContent = 'EDITAR TARIFA';
    document.getElementById('dialog-title').textContent = 'Edita tarifa';
    submitButton.textContent = 'Guardar cambios';
    tariffType.value = tariff.type;
    updateEnergyFields(tariff.type, tariff.energy);
    tariffForm.elements.namedItem('name').value = tariff.name;
    tariffForm.elements.namedItem('powerPeak').value = tariff.powerPeak;
    tariffForm.elements.namedItem('powerValley').value = tariff.powerValley;
    tariffForm.elements.namedItem('fee').value = tariff.fee;
  } else {
    document.getElementById('dialog-context').textContent = 'NUEVA OFERTA';
    document.getElementById('dialog-title').textContent = 'Añade una tarifa';
    submitButton.innerHTML = 'Añadir a la comparación <span aria-hidden="true">→</span>';
    tariffType.value = 'flat';
    updateEnergyFields('flat');
  }

  dialog.showModal();
}

document.getElementById('open-dialog').addEventListener('click', () => openTariffDialog());
document.getElementById('close-dialog').addEventListener('click', () => dialog.close());
document.getElementById('cancel-dialog').addEventListener('click', () => dialog.close());
tariffType.addEventListener('change', (event) => updateEnergyFields(event.target.value));
tariffForm.addEventListener('submit', (event) => {
  event.preventDefault();
  const form = new FormData(event.currentTarget);
  const type = form.get('type');
  const energy = {};
  for (const key of ['peak', 'flat', 'valley']) {
    const value = form.get(`energy-${key}`);
    if (value !== null) energy[key] = Number(value);
  }
  const updatedTariff = {
    name: String(form.get('name')).trim(),
    type,
    energy,
    powerPeak: Number(form.get('powerPeak')),
    powerValley: Number(form.get('powerValley')),
    fee: Number(form.get('fee')) || 0,
    custom: true,
  };

  if (editingTariffId) {
    const tariffIndex = tariffs.findIndex((tariff) => tariff.id === editingTariffId);
    if (tariffIndex !== -1) tariffs[tariffIndex] = { ...tariffs[tariffIndex], ...updatedTariff };
  } else {
    tariffs.push({ ...updatedTariff, id: `custom-${Date.now()}` });
  }

  renderTariffs();
  editingTariffId = null;
  dialog.close();
});

updateEnergyFields('flat');
renderTariffs();
